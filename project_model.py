# project/models.py
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q, UniqueConstraint
from django.contrib.postgres.fields import ArrayField
from requestforproposalbackend.base_model import BaseModel


class TenantOwnedMixin(models.Model):
    """
    • organization = NULL  → global / public row
    • organization != NULL → private to that tenant
    """
    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="%(class)s_rows",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        editable=False,
        related_name="%(class)s_created",
    )

    class Meta:
        abstract = True


class OrgVisibilityMixin(models.Model):
    """
    Optional “block‑list” for global rows – tenants in this M2M
    must NOT see the row in their catalogue.
    """
    blocked_for = models.ManyToManyField(
        "authentication.Organization",
        blank=True,
        related_name="%(class)s_blocked",
        help_text="Tenants that should NOT see this public row.",
    )

    class Meta:
        abstract = True


class TenantAwareQuerySet(models.QuerySet):
    def visible_to(self, org):
        # 1) org‑scoped filter
        if org is None:
            qs = self.filter(organization__isnull=True)
        else:
            qs = self.filter(
                Q(organization__isnull=True) |
                Q(organization=org)
            )
        # 2) optional block‑list for global rows
        if hasattr(self.model, "blocked_for"):
            qs = qs.exclude(blocked_for=org)
        return qs


class TenantAwareManager(models.Manager):
    def get_queryset(self):
        return TenantAwareQuerySet(self.model, using=self._db)

    def visible_to(self, org):
        return self.get_queryset().visible_to(org)


# ──────────────────────────────────────────────────────────────
#  Canonical tenant‑aware tables
# ──────────────────────────────────────────────────────────────
class Industry(TenantOwnedMixin, OrgVisibilityMixin, BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')
    url = models.CharField(max_length=200, blank=True, default='')

    objects = TenantAwareManager()

    class Meta:
        constraints = [
            UniqueConstraint(fields=['organization', 'name'], name='unique_tenant_industry_name')
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Service(TenantOwnedMixin, BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField()

    objects = TenantAwareManager()

    class Meta:
        constraints = [
            UniqueConstraint(fields=['organization', 'name'], name='unique_tenant_service_name')
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class BusinessCycle(TenantOwnedMixin, BaseModel):
    order = models.IntegerField(default=1)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')

    objects = TenantAwareManager()

    class Meta:
        constraints = [
            UniqueConstraint(fields=['organization', 'name'], name='unique_tenant_businesscycle_name')
        ]
        ordering = ["organization_id", "order"]

    def __str__(self):
        return self.name


class FunctionalArea(TenantOwnedMixin, BaseModel):
    business_cycle = models.ForeignKey(BusinessCycle, on_delete=models.CASCADE)
    order = models.IntegerField(default=1)
    name = models.CharField(max_length=180)
    description = models.TextField()

    objects = TenantAwareManager()

    class Meta:
        constraints = [
            UniqueConstraint(fields=['organization', 'name'], name='unique_tenant_functionalarea_name')
        ]
        ordering = ["business_cycle__order", "order"]

    def __str__(self):
        return self.name


class Provider(TenantOwnedMixin, BaseModel):
    company_name = models.CharField(max_length=100)
    contact_name = models.CharField(max_length=100)
    contact_phone = models.CharField(max_length=100)
    contact_email = models.CharField(max_length=100)

    objects = TenantAwareManager()

    class Meta:
        constraints = [
            UniqueConstraint(fields=['organization', 'company_name'], name='unique_tenant_provider_name')
        ]
        ordering = ["company_name"]

    def __str__(self):
        return self.company_name


# ──────────────────────────────────────────────────────────────
#  RFP‑specific models
# ──────────────────────────────────────────────────────────────
class ProjectGeneratedRFPService(models.Model):
    generated_rfp = models.ForeignKey(
        "project.GeneratedRFP",
        on_delete=models.CASCADE,
        null=True, blank=True,
    )
    service = models.ForeignKey(
        "project.Service",
        on_delete=models.PROTECT,
        null=True, blank=True,
    )

    class Meta:
        db_table = "project_generatedrfp_services"
        constraints = [
            UniqueConstraint(fields=['generated_rfp', 'service'], name='unique_rfp_service')
        ]


class ProjectGeneratedRFPBusinessCycle(models.Model):
    generated_rfp = models.ForeignKey(
        "project.GeneratedRFP",
        db_column="generated_rfp_id",
        on_delete=models.CASCADE,
    )
    business_cycle = models.ForeignKey(
        "project.BusinessCycle",
        db_column="business_cycle_id",
        on_delete=models.PROTECT,
    )

    class Meta:
        db_table = "project_generatedrfp_business_cycles"
        constraints = [
            UniqueConstraint(fields=["generated_rfp", "business_cycle"], name="unique_rfp_business_cycle"),
        ]


class GeneratedRFP(BaseModel):
    status = models.CharField(max_length=100, default="in-progress", blank=True)
    start_date = models.DateField(auto_now_add=True, blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    rfp_name = models.CharField(max_length=100)
    rfp_description = models.TextField()
    company_url = models.CharField(max_length=100, blank=True, default='')
    value_propositions = models.CharField(max_length=260)

    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        related_name="generated_rfps",
        null=True, blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_rfps",
    )
    allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="accessible_rfps",
    )

    industry = models.ForeignKey("project.Industry", on_delete=models.CASCADE)

    services = models.ManyToManyField(
        "project.Service",
        through="project.ProjectGeneratedRFPService",
        related_name="rfp_services",
    )

    questionnaires = models.JSONField(default=list)
    business_cycles = models.ManyToManyField(
        "project.BusinessCycle",
        through="project.ProjectGeneratedRFPBusinessCycle",
    )

    areas = models.ManyToManyField(
        "project.FunctionalArea",
        through="project.ProjectGeneratedRFPArea",
        related_name="rfp_areas",
    )

    descriptions = models.JSONField(default=list)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        org_name = self.organization.name if self.organization else "Unassigned"
        return f"{self.rfp_name} ({org_name})"


class ProjectGeneratedRFPArea(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    generated_rfp = models.ForeignKey(
        "project.GeneratedRFP",
        db_column="generated_rfp_id",
        on_delete=models.CASCADE,
    )
    area = models.ForeignKey(
        "project.FunctionalArea",
        db_column="functional_area_id",
        on_delete=models.PROTECT,
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )

    class Meta:
        db_table = "project_generatedrfp_areas"
        constraints = [
            UniqueConstraint(fields=['generated_rfp', 'area'], name='unique_rfp_area')
        ]

    def __str__(self):
        return f"RFP {self.generated_rfp_id} → Area {self.area_id}"


class SubmittedRFP(BaseModel):
    rfp = models.ForeignKey("project.GeneratedRFP", on_delete=models.CASCADE, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True)

    status = models.CharField(max_length=100, default="in-progress", blank=True)
    last_login_to_rfp = models.DateField(auto_now_add=True, null=True, blank=True)
    last_login_ip_address = models.CharField(max_length=100, blank=True, default='')
    pdf_link = models.CharField(max_length=10000, blank=True, default='')
    is_opened = models.BooleanField(default=False)
    recived_person = models.CharField(max_length=100)
    recived_person_email = models.CharField(max_length=100)

    def __str__(self):
        return f"SubmittedRFP {self.id} for RFP {self.rfp.id if self.rfp else 'N/A'}"


class FunctionalAreaEmbedding(models.Model):
    area_name = models.CharField(max_length=255)
    text = models.TextField()
    embedding = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.area_name


class FinalizedRFP(BaseModel):
    """
    The FINALIZED, IMMUTABLE version of an RFP.
    This is created from a GeneratedRFP and serves as a permanent, point-in-time snapshot.
    """
    # --- Metadata for filtering and access ---
    source_rfp = models.ForeignKey(GeneratedRFP, on_delete=models.SET_NULL, null=True,
                                   related_name="finalized_versions")
    organization = models.ForeignKey("authentication.Organization", on_delete=models.CASCADE,
                                     related_name="finalized_rfps")
    # user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
    #                          related_name="finalized_by")
    status = models.CharField(max_length=100, default="finalized", blank=True)

    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    # --- The immutable snapshot of all content ---
    snapshot_data = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.snapshot_data.get('rfp_name', 'Finalized RFP')} ({self.id})"


class ResponseRFP(BaseModel):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE)
    rfp = models.ForeignKey(GeneratedRFP, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    submitted_rfp = models.ForeignKey(SubmittedRFP, on_delete=models.CASCADE)

    completed_fields = models.JSONField(default=list)
    response_fields = models.JSONField(default=list)

    is_accepted = models.BooleanField(default=False)
    is_rejected = models.BooleanField(default=False)
    is_pending = models.BooleanField(default=True)

    status = models.CharField(max_length=100, default="in-progress", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ResponseRFP {self.id} for RFP {self.rfp.id}"


class ProjectFunctionalAreaSession(BaseModel):
    session_id = models.CharField(max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    functional_area = models.ForeignKey(FunctionalArea, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"FA Session {self.session_id}"


class FileMetadata(models.Model):
    file_name = models.CharField(max_length=255)
    file_url = models.URLField(max_length=2000)
    file_path = models.CharField(max_length=512, blank=True, default="")
    questions_count = models.IntegerField(default=0)
    description = models.TextField(blank=True, default='')
    tags = ArrayField(models.CharField(max_length=100), blank=True, default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_name} ({self.id})"
