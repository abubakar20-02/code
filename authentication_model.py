# authentication/models.py
from __future__ import annotations

from django.contrib.auth.models import AbstractUser, Group
from django.db import models
from django.db.models.signals import pre_save, post_save, m2m_changed
from django.dispatch import receiver
from django.utils import timezone

from requestforproposalbackend.base_model import BaseModel


# ──────────────────────────────────────────────────────────────
#  ORGANIZATION
# ──────────────────────────────────────────────────────────────
class Organization(BaseModel):
    name = models.CharField(max_length=100)
    domain = models.CharField(max_length=100, default="none")

    def __str__(self) -> str:  # type: ignore[override]
        return self.name


# ──────────────────────────────────────────────────────────────
#  ROLE  (proxy around auth_group)
# ──────────────────────────────────────────────────────────────
class Role(Group):
    """Alias for *auth_group* so we can call them “Roles” instead of “Groups”."""

    class Meta:
        proxy = True
        verbose_name = "Role"
        verbose_name_plural = "Roles"

    @property
    def is_super_role(self) -> bool:
        return self.name.lower() in {"super_admin"}


# ──────────────────────────────────────────────────────────────
#  USER  — single-role FK + normal groups M2M
# ──────────────────────────────────────────────────────────────
class User(AbstractUser):
    email = models.EmailField(unique=True)

    role = models.ForeignKey(  # primary / “role” group
        Group,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="role_users",
        help_text="Single group that represents the user's role",
    )

    # extra business columns
    value_propositions = models.CharField(max_length=100, default="system")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=True, blank=True
    )
    user_uid_outseta = models.CharField(max_length=100, null=True, blank=True)

    # NO save() override — all syncing handled in signals

    def __str__(self) -> str:  # type: ignore[override]
        return self.email or self.username

    class Meta(AbstractUser.Meta):
        # granular perms (optional but useful)
        permissions = [
            ("view_user_in_organization", "Can view users in same organization"),
        ]


# ──────────────────────────────────────────────────────────────
#  BIDIRECTIONAL role  ↔  groups SYNC (signals)
# ──────────────────────────────────────────────────────────────
@receiver(pre_save, sender=User)
def _remember_desired_role(sender, instance: User, **__) -> None:
    """Cache intended `role_id` so we can update M2M after PK exists."""
    instance._desired_role_id = instance.role_id


@receiver(post_save, sender=User)
def _sync_role_to_groups(sender, instance: User, **__) -> None:
    """After save, make M2M match the *current* role FK."""
    rid = getattr(instance, "_desired_role_id", None)
    if rid is None:
        return
    instance.groups.set([rid] if rid else [])
    del instance._desired_role_id


@receiver(m2m_changed, sender=User.groups.through)
def _sync_groups_to_role(sender, instance: User, action: str, pk_set, **__) -> None:
    """When groups change, promote the first group (if any) to `.role`."""
    if action not in {"post_add", "post_remove", "post_clear"}:
        return

    new_role_id = (
        next(iter(pk_set), None)  # explicit add/remove
        if pk_set else
        instance.groups.order_by("pk").values_list("pk", flat=True).first()
    )

    if instance.role_id != new_role_id:
        User.objects.filter(pk=instance.pk).update(role=new_role_id)  # bypass signals


# ──────────────────────────────────────────────────────────────
#  REMAINING MODELS (unchanged)
# ──────────────────────────────────────────────────────────────
class PasswordResetToken(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=100)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)


class UserBusinessCycleAssignment(BaseModel):
    """
    Assigns a BusinessCycle to a User within the context of an Organization.
    Ensures that for any given organization, a business cycle can only be
    assigned to a single user.
    """
    user = models.ForeignKey(
        "authentication.User",
        on_delete=models.CASCADE,
        related_name="business_cycle_assignments",
        null=True
    )
    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        related_name="user_business_cycle_assignments",
        null=True
    )
    business_cycle = models.ForeignKey(
        "project.BusinessCycle",
        on_delete=models.CASCADE,
        related_name="user_assignments",
        null=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'business_cycle'],
                name='unique_org_business_cycle_assignment'
            )
        ]

    def __str__(self) -> str:
        return f"Assignment for {self.user} in {self.organization} to {self.business_cycle}"


class Invite(BaseModel):
    inviter = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_invites")
    email = models.EmailField()
    hashed_token = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField()

    def is_valid(self) -> bool:
        return self.is_active and self.expires_at > timezone.now()

    def deactivate(self) -> None:
        self.is_active = False
        self.save(update_fields=["is_active"])
