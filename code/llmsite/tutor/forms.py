from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import StudentProfile

class StudentInitForm(forms.Form):
    studentName = forms.CharField(max_length=100)
    studentSchool = forms.CharField(max_length=200, required=False)
    studentGrade = forms.CharField(max_length=50, required=False)
    studentClasses = forms.CharField(widget=forms.Textarea, required=False)

class MessageForm(forms.Form):
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))

class SignupForm(UserCreationForm):
    school = forms.CharField(max_length=200, required=False)
    grade = forms.CharField(max_length=50, required=False)
    classes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ("email",)

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            StudentProfile.objects.create(
                user=user,
                school=self.cleaned_data.get("school"),
                grade=self.cleaned_data.get("grade"),
                classes=self.cleaned_data.get("classes")
            )
        return user
    
class UploadRagForm(forms.Form):
    title = forms.CharField(max_length=100)
    file = forms.FileField()