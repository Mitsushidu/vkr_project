from django import forms


class ChatMessageForm(forms.Form):
    content = forms.CharField(
        label="Сообщение",
        max_length=4000,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Опишите правовую ситуацию или задайте вопрос...",
                "class": "chat-textarea",
            }
        ),
    )
