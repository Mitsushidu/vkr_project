import csv
import json
import re

from django.core.management.base import BaseCommand, CommandError

from knowledge.models import LegalDocument, LegalFragment


ARTICLE_HEADING_RE = re.compile(
    r"(?m)^\s*(Статья\s+\d+(?:\.\d+)*[^\n]*)",
    re.IGNORECASE,
)
ARTICLE_NUMBER_RE = re.compile(r"Статья\s+(\d+(?:\.\d+)*)", re.IGNORECASE)
CHUNK_SIZE = 3500
LONG_TEXT_LIMIT = 6000


def split_text_to_fragments(text):
    text = (text or "").strip()
    if not text:
        return [
            {
                "article_number": "",
                "heading": "",
                "text": "",
                "fragment_type": "plain_text",
            }
        ]

    article_matches = list(ARTICLE_HEADING_RE.finditer(text))
    if article_matches:
        fragments = []
        preamble = text[: article_matches[0].start()].strip()
        if preamble:
            for chunk in _chunk_text(preamble):
                fragments.append(
                    {
                        "article_number": "",
                        "heading": "",
                        "text": chunk,
                        "fragment_type": "plain_text",
                    }
                )

        for index, match in enumerate(article_matches):
            start = match.start()
            end = article_matches[index + 1].start() if index + 1 < len(article_matches) else len(text)
            article_text = text[start:end].strip()
            heading = match.group(1).strip()
            number_match = ARTICLE_NUMBER_RE.search(heading)
            article_number = number_match.group(1) if number_match else ""

            for chunk in _chunk_text(article_text):
                fragments.append(
                    {
                        "article_number": article_number,
                        "heading": heading,
                        "text": chunk,
                        "fragment_type": "article",
                    }
                )
        return fragments

    return [
        {
            "article_number": "",
            "heading": "",
            "text": chunk,
            "fragment_type": "plain_text",
        }
        for chunk in _chunk_text(text)
    ]


def _chunk_text(text):
    if len(text) <= LONG_TEXT_LIMIT:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            split_at = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
            if split_at > start + 1000:
                end = split_at
        chunks.append(text[start:end].strip())
        start = end
    return [chunk for chunk in chunks if chunk]


class Command(BaseCommand):
    help = "Импортирует нормативные документы и фрагменты из CSV или RusLawOD"

    def add_arguments(self, parser):
        parser.add_argument("--csv", dest="csv_path", help="Путь к CSV-файлу с фрагментами")
        parser.add_argument("--hf", action="store_true", help="Импортировать RusLawOD из Hugging Face")
        parser.add_argument("--limit", type=int, default=100, help="Максимум документов/фрагментов для HF")
        parser.add_argument(
            "--keyword",
            default="",
            help=(
                "Фильтр по слову в названии или тексте для HF. "
                'Пример: python manage.py import_legal_fragments --hf --limit 100 --keyword "Статья 228"'
            ),
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Заменять фрагменты уже импортированных документов",
        )

    def handle(self, *args, **options):
        csv_path = options.get("csv_path")
        use_hf = options.get("hf")

        if bool(csv_path) == bool(use_hf):
            raise CommandError("Укажите ровно один режим: --csv path или --hf")

        if csv_path:
            self.stdout.write(f"Режим импорта: CSV")
            self.stdout.write(f"Файл: {csv_path}")
            self.stdout.write(f"Keyword: не используется; limit: без ограничения")
            stats = self.import_csv(csv_path, replace=options["replace"])
        else:
            self.stdout.write(f"Режим импорта: Hugging Face")
            self.stdout.write(f"Keyword: {options['keyword'] or 'не задан'}; limit: {options['limit']}")
            stats = self.import_hf(
                limit=options["limit"],
                keyword=options["keyword"],
                replace=options["replace"],
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Импорт завершён:\n"
                f"создано документов: {stats['documents_created']}\n"
                f"пропущено дублей: {stats['duplicates_skipped']}\n"
                f"создано фрагментов: {stats['fragments_created']}\n"
                f"пропущено пустых документов: {stats['empty_skipped']}"
            )
        )

    def import_csv(self, csv_path, replace=False):
        stats = self.empty_stats()

        try:
            csv_file = open(csv_path, newline="", encoding="utf-8-sig")
        except OSError as exc:
            raise CommandError(f"Не удалось открыть CSV-файл: {exc}") from exc

        with csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                _, fragment_count, result = self.create_document_with_fragments(
                    title=self.get_value(row, "title") or "Без названия",
                    document_type=self.get_value(row, "document_type"),
                    source_uid=self.get_value(row, "source_uid"),
                    keywords=self.get_value(row, "keywords"),
                    raw_text=self.get_value(row, "text"),
                    category_hint=self.get_value(row, "category_hint"),
                    article_number=self.get_value(row, "article_number"),
                    heading=self.get_value(row, "heading"),
                    source_name="CSV",
                    replace=replace,
                )
                self.update_stats(stats, result, fragment_count)

        return stats

    def import_hf(self, limit, keyword, replace=False):
        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise CommandError(
                "Для импорта из Hugging Face установите библиотеку datasets."
            ) from exc

        if limit < 1:
            raise CommandError("--limit должен быть положительным числом")

        dataset = load_dataset("irlspbru/RusLawOD", split="train", streaming=True)
        keyword = (keyword or "").lower()
        stats = self.empty_stats()
        imported_documents = 0

        for row in dataset:
            if imported_documents >= limit or stats["fragments_created"] >= limit:
                break

            title = self.get_value(row, "headingIPS") or "Без названия"
            text = self.get_value(row, "textIPS")
            if keyword and keyword not in f"{title}\n{text}".lower():
                continue

            remaining_fragments = limit - stats["fragments_created"]
            _, fragment_count, result = self.create_document_with_fragments(
                title=title,
                document_type=self.get_value(row, "doc_typeIPS"),
                source_uid=self.get_value(row, "pravogovruNd"),
                status=self.get_value(row, "statusIPS"),
                keywords=self.get_value(row, "keywordsByIPS"),
                classifier=self.get_value(row, "classifierByIPS"),
                raw_text=text,
                source_name="RusLawOD",
                max_fragments=remaining_fragments,
                replace=replace,
            )
            self.update_stats(stats, result, fragment_count)
            if result in {"created", "replaced"}:
                imported_documents += 1

        return stats

    def create_document_with_fragments(
        self,
        *,
        title,
        raw_text,
        document_type="",
        source_uid="",
        status="",
        keywords="",
        classifier="",
        category_hint="",
        article_number="",
        heading="",
        source_name="RusLawOD",
        max_fragments=None,
        replace=False,
    ):
        raw_text = self.stringify_value(raw_text)
        title = self.stringify_value(title)
        document_type = self.stringify_value(document_type)
        source_uid = self.stringify_value(source_uid)
        status = self.stringify_value(status)
        keywords = self.stringify_value(keywords)
        classifier = self.stringify_value(classifier)
        category_hint = self.stringify_value(category_hint)
        article_number = self.stringify_value(article_number)
        heading = self.stringify_value(heading)
        source_name = self.stringify_value(source_name)

        if not raw_text or not raw_text.strip():
            return None, 0, "empty"

        source_uid = source_uid[:255]
        title = (title or "Без названия")[:500]
        source_name = source_name[:100]
        existing_query = {"source_name": source_name}
        if source_uid:
            existing_query["source_uid"] = source_uid
        else:
            existing_query["title"] = title

        document = LegalDocument.objects.filter(**existing_query).first()
        if document and not replace:
            self.stdout.write(f"Пропущен дубль: {document}")
            return document, 0, "duplicate"

        document_values = {
            "source_uid": source_uid,
            "title": title,
            "document_type": document_type[:255],
            "status": status[:255],
            "keywords": keywords,
            "classifier": classifier,
            "raw_text": raw_text,
            "source_name": source_name,
        }
        if document:
            for field, value in document_values.items():
                setattr(document, field, value)
            document.save()
            document.fragments.all().delete()
            result = "replaced"
        else:
            document = LegalDocument.objects.create(**document_values)
            result = "created"

        fragments = split_text_to_fragments(raw_text)
        if max_fragments is not None:
            fragments = fragments[:max_fragments]

        fragment_objects = []
        for order, fragment in enumerate(fragments, start=1):
            fragment_objects.append(
                LegalFragment(
                    document=document,
                    fragment_type=fragment["fragment_type"],
                    fragment_order=order,
                    article_number=(fragment["article_number"] or article_number)[:100],
                    heading=(fragment["heading"] or heading)[:500],
                    text=fragment["text"],
                    category_hint=category_hint[:255],
                )
            )

        LegalFragment.objects.bulk_create(fragment_objects)
        return document, len(fragment_objects), result

    def update_stats(self, stats, result, fragment_count):
        if result == "created":
            stats["documents_created"] += 1
        elif result == "duplicate":
            stats["duplicates_skipped"] += 1
        elif result == "empty":
            stats["empty_skipped"] += 1

        stats["fragments_created"] += fragment_count
        self.report_progress(stats)

    def report_progress(self, stats):
        documents = stats["documents_created"]
        fragments = stats["fragments_created"]
        while documents >= stats["next_document_progress"]:
            self.stdout.write(
                f"Прогресс: создано документов: {stats['next_document_progress']}"
            )
            stats["next_document_progress"] += 10
        while fragments >= stats["next_fragment_progress"]:
            self.stdout.write(
                f"Прогресс: создано фрагментов: {stats['next_fragment_progress']}"
            )
            stats["next_fragment_progress"] += 10

    @staticmethod
    def empty_stats():
        return {
            "documents_created": 0,
            "duplicates_skipped": 0,
            "fragments_created": 0,
            "empty_skipped": 0,
            "next_document_progress": 10,
            "next_fragment_progress": 10,
        }

    @staticmethod
    def get_value(row, key):
        return Command.stringify_value(row.get(key, ""))

    @staticmethod
    def stringify_value(value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item).strip() for item in value if item is not None)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip()
