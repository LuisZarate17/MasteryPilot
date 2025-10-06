from django import forms

class StudentInitForm(forms.Form):
    studentName = forms.CharField(max_length=100)
    studentSchool = forms.CharField(max_length=200, required=False)
    studentGrade = forms.CharField(max_length=50, required=False)
    studentClasses = forms.CharField(widget=forms.Textarea, required=False)

class MessageForm(forms.Form):
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))