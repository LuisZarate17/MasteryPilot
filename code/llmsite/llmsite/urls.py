"""
URL configuration for llmsite project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.contrib.auth import views as auth_views


urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    
    # Password reset views
    path("accounts/password-reset/", 
         auth_views.PasswordResetView.as_view(
             template_name="registration/password_reset_form.html",
             email_template_name="registration/password_reset_email.html",
             success_url="/accounts/password-reset/done/"
         ), 
         name="password_reset"),
    path("accounts/password-reset/done/", 
         auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"), 
         name="password_reset_done"),
    path("accounts/password-reset/<uidb64>/<token>/", 
         auth_views.PasswordResetConfirmView.as_view(
             template_name="registration/password_reset_confirm.html",
             success_url="/accounts/password-reset/complete/"
         ), 
         name="password_reset_confirm"),
    path("accounts/password-reset/complete/", 
         auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"), 
         name="password_reset_complete"),
    
    path("tutor/", include("tutor.urls")),
    path('admin/', admin.site.urls),
    path('', include('tutor.urls')),
]
