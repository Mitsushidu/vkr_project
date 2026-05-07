from datasets import load_dataset

ds = load_dataset("irlspbru/RusLawOD", split="train", streaming=True)
row = next(iter(ds))
print(row.keys())
print(row.get("headingIPS"))
print((row.get("textIPS") or "")[:1000])
