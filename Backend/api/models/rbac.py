from django.db import models
from django.utils import timezone


class Permission(models.Model):
    """Master catalog of every permission code the app checks against."""
    permission_id = models.AutoField(primary_key=True)
    permission_code = models.CharField(max_length=60, unique=True,
                                       help_text="e.g. user.view, user.create, user.edit")
    module = models.CharField(max_length=40,
                              help_text="Grouping for UI: Users, Batches, Candidates, etc.")
    description = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'permissions'
        ordering = ['module', 'permission_code']

    def __str__(self):
        return self.permission_code


class Role(models.Model):
    """Fixed set of system roles with permissions from role_permissions."""
    role_id = models.AutoField(primary_key=True)
    role_name = models.CharField(max_length=50, unique=True)
    role_code = models.CharField(max_length=30, unique=True,
                                 help_text="e.g. 'admin', 'ta'")
    description = models.CharField(max_length=255, null=True, blank=True)
    priority = models.SmallIntegerField(default=0,
                                        help_text="Higher = more privileged")
    is_system = models.BooleanField(default=True,
                                    help_text="System roles can't be deleted from UI")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'roles'
        ordering = ['-priority', 'role_name']

    def __str__(self):
        return self.role_name


class RolePermission(models.Model):
    """Junction table for RBAC matrix."""
    role = models.ForeignKey(Role, on_delete=models.CASCADE, db_column='role_id')
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE,
                                   db_column='permission_id')

    class Meta:
        db_table = 'role_permissions'
        unique_together = ['role', 'permission']

    def __str__(self):
        return f"{self.role.role_name} - {self.permission.permission_code}"