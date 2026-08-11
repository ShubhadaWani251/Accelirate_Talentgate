from django.db import models
from django.utils import timezone
from .users import User


class Setting(models.Model):
    """Generic key-value store for global configuration."""
    setting_id = models.AutoField(primary_key=True)
    setting_key = models.CharField(max_length=100, unique=True)
    setting_value = models.CharField(max_length=255)
    setting_group = models.CharField(max_length=40,
                                     help_text="exam_config, duplicate_check, etc.")
    is_editable = models.BooleanField(default=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL,
                                   null=True, db_column='updated_by')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'settings'
        constraints = [
            models.UniqueConstraint(fields=['setting_key'],
                                   name='ux_settings_key')
        ]

    def __str__(self):
        return f"{self.setting_key} = {self.setting_value}"