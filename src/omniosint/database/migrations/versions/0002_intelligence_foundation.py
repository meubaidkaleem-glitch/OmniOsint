"""Core intelligence foundation: entities, evidence, sources, raw responses,
providers, collection requests and jobs, scopes, search history.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Evidence is append-only, like the audit trail. UPDATE is always refused.
# DELETE and TRUNCATE are refused unless the transaction has opted in, which
# only the retention job does (SET LOCAL omniosint.evidence_purge = 'on').
_EVIDENCE_GUARD_FUNCTION = """
CREATE FUNCTION omniosint_evidence_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE')
       AND current_setting('omniosint.evidence_purge', true) IS NOT DISTINCT FROM 'on' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'evidence is append-only (% refused)', TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""

_EVIDENCE_GUARD_TRIGGERS = (
    """
    CREATE TRIGGER evidence_append_only
    BEFORE UPDATE OR DELETE ON evidence
    FOR EACH ROW EXECUTE FUNCTION omniosint_evidence_guard()
    """,
    """
    CREATE TRIGGER evidence_no_truncate
    BEFORE TRUNCATE ON evidence
    FOR EACH STATEMENT EXECUTE FUNCTION omniosint_evidence_guard()
    """,
)


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("canonical_key", sa.String(length=2048), nullable=False),
        sa.Column("display_name", sa.String(length=2048), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("merged_into_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('person_reference', 'email', 'phone', 'username', 'domain', 'subdomain', 'url', 'ip_address', 'network_prefix', 'asn', 'organization', 'router', 'switch', 'firewall', 'server', 'access_point', 'endpoint', 'cloud_asset', 'certificate', 'image', 'document', 'file_hash', 'repository', 'package', 'vulnerability', 'threat_indicator', 'malware_sample', 'public_event', 'geographic_location')",
            name=op.f("ck_entities_type_valid"),
        ),
        sa.CheckConstraint(
            "length(canonical_key) > 0", name=op.f("ck_entities_canonical_key_not_empty")
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_id"],
            ["entities.id"],
            name=op.f("fk_entities_merged_into_id_entities"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
        sa.UniqueConstraint("type", "canonical_key", name="uq_entities_type_canonical_key"),
    )
    op.create_index("ix_entities_last_observed_at", "entities", ["last_observed_at"], unique=False)
    op.create_table(
        "evidence_sources",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("homepage_url", sa.String(length=512), nullable=True),
        sa.Column(
            "reliability",
            sa.String(length=16),
            server_default=sa.text("'unassessed'"),
            nullable=False,
        ),
        sa.Column(
            "upstream_source_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("terms_note", sa.Text(), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(upstream_source_ids) = 'array'",
            name=op.f("ck_evidence_sources_upstream_is_array"),
        ),
        sa.CheckConstraint(
            "kind IN ('api', 'dataset', 'tool', 'local', 'analyst', 'upload', 'simulated')",
            name=op.f("ck_evidence_sources_kind_valid"),
        ),
        sa.CheckConstraint(
            "reliability IN ('unassessed', 'high', 'medium', 'low')",
            name=op.f("ck_evidence_sources_reliability_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_sources")),
    )
    op.create_table(
        "providers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("adapter_version", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_health", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_providers")),
    )
    op.create_table(
        "raw_objects",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("encryption", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_raw_objects_sha256_hex")),
        sa.CheckConstraint("size >= 0", name=op.f("ck_raw_objects_size_not_negative")),
        sa.PrimaryKeyConstraint("sha256", name=op.f("pk_raw_objects")),
    )
    op.create_index("ix_raw_objects_retain_until", "raw_objects", ["retain_until"], unique=False)
    op.create_table(
        "provider_usage",
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("capability", sa.String(length=96), nullable=False),
        sa.Column("requests", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cache_hits", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "credits",
            sa.Numeric(precision=14, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["providers.id"],
            name=op.f("fk_provider_usage_provider_id_providers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("provider_id", "day", "capability", name=op.f("pk_provider_usage")),
    )
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("indicator_type", sa.String(length=32), nullable=True),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_saved_searches_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_searches")),
        sa.UniqueConstraint("user_id", "name", name="uq_saved_searches_user_id_name"),
    )
    op.create_table(
        "scopes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("authorized_by", sa.String(length=256), nullable=False),
        sa.Column("authorization_reference", sa.String(length=256), nullable=True),
        sa.Column("authorization_note", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("revoke_reason", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode IN ('passive', 'authorized_discovery', 'active_assessment')",
            name=op.f("ck_scopes_mode_valid"),
        ),
        sa.CheckConstraint(
            "length(trim(authorized_by)) > 0", name=op.f("ck_scopes_authorized_by_given")
        ),
        sa.CheckConstraint("valid_until > valid_from", name=op.f("ck_scopes_validity_ordered")),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_scopes_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_scopes_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["users.id"],
            name=op.f("fk_scopes_revoked_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scopes")),
    )
    op.create_index("ix_scopes_valid_until", "scopes", ["valid_until"], unique=False)
    op.create_table(
        "search_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "types",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_search_history_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_history")),
    )
    op.create_index(
        "ix_search_history_user_id_created_at",
        "search_history",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "collection_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("indicator_type", sa.String(length=32), nullable=False),
        sa.Column("indicator_value", sa.String(length=2048), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("strategy", sa.String(length=24), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "indicator_type IN ('email', 'phone', 'username', 'domain', 'url', 'ipv4', 'ipv6', 'ip_range', 'asn', 'network_prefix', 'organization', 'business_name', 'file_hash', 'file', 'image', 'document', 'certificate_fingerprint', 'social_profile_url', 'repository_url', 'package', 'cve', 'malware_indicator', 'coordinates', 'question')",
            name=op.f("ck_collection_requests_indicator_type_valid"),
        ),
        sa.CheckConstraint(
            "mode IN ('passive', 'active')", name=op.f("ck_collection_requests_mode_valid")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'awaiting_approval', 'running', 'completed', 'partial', 'failed', 'cancelled')",
            name=op.f("ck_collection_requests_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_collection_requests_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_collection_requests_entity_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["scopes.id"],
            name=op.f("fk_collection_requests_scope_id_scopes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_requests")),
    )
    op.create_index(
        "ix_collection_requests_created_at_id",
        "collection_requests",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_collection_requests_created_by", "collection_requests", ["created_by"], unique=False
    )
    op.create_index(
        "ix_collection_requests_entity_id", "collection_requests", ["entity_id"], unique=False
    )
    op.create_table(
        "scope_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=2048), nullable=False),
        sa.Column("is_exclusion", sa.Boolean(), nullable=False),
        sa.Column(
            "restrictions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('domain', 'wildcard', 'ip', 'cidr', 'url_prefix')",
            name=op.f("ck_scope_rules_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["scopes.id"],
            name=op.f("fk_scope_rules_scope_id_scopes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scope_rules")),
        sa.UniqueConstraint(
            "scope_id", "kind", "value", "is_exclusion", name="uq_scope_rules_scope_id_kind_value"
        ),
    )
    op.create_table(
        "collection_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("indicator_type", sa.String(length=32), nullable=False),
        sa.Column("indicator_value", sa.String(length=2048), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("capability", sa.String(length=96), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "progress",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "cost",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("cache_key", sa.String(length=512), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "indicator_type IN ('email', 'phone', 'username', 'domain', 'url', 'ipv4', 'ipv6', 'ip_range', 'asn', 'network_prefix', 'organization', 'business_name', 'file_hash', 'file', 'image', 'document', 'certificate_fingerprint', 'social_profile_url', 'repository_url', 'package', 'cve', 'malware_indicator', 'coordinates', 'question')",
            name=op.f("ck_collection_jobs_indicator_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'awaiting_approval', 'running', 'succeeded', 'failed', 'cancelled', 'skipped')",
            name=op.f("ck_collection_jobs_status_valid"),
        ),
        sa.CheckConstraint(
            "NOT is_active OR scope_id IS NOT NULL",
            name=op.f("ck_collection_jobs_active_jobs_have_a_scope"),
        ),
        sa.CheckConstraint(
            "attempt >= 0 AND max_attempts >= 1", name=op.f("ck_collection_jobs_attempts_valid")
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_collection_jobs_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_collection_jobs_entity_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["collection_requests.id"],
            name=op.f("fk_collection_jobs_request_id_collection_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_collection_jobs_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["scopes.id"],
            name=op.f("fk_collection_jobs_scope_id_scopes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_jobs")),
    )
    op.create_index(
        "ix_collection_jobs_created_at_id", "collection_jobs", ["created_at", "id"], unique=False
    )
    op.create_index(
        "ix_collection_jobs_leases",
        "collection_jobs",
        ["lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_collection_jobs_queue",
        "collection_jobs",
        ["priority", "scheduled_at"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "ix_collection_jobs_request_id", "collection_jobs", ["request_id"], unique=False
    )
    op.create_index("ix_collection_jobs_status", "collection_jobs", ["status"], unique=False)
    op.create_table(
        "collection_job_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=1024), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["collection_jobs.id"],
            name=op.f("fk_collection_job_events_job_id_collection_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_job_events")),
    )
    op.create_index(
        "ix_collection_job_events_job_id_occurred_at",
        "collection_job_events",
        ["job_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "collection_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("capability", sa.String(length=96), nullable=False),
        sa.Column("page", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_size", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("normalized", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("item_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("normalization_error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("from_cache", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reused_result_id", sa.Uuid(), nullable=True),
        sa.Column("cache_key", sa.String(length=512), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "raw_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_collection_results_raw_hex")
        ),
        sa.CheckConstraint(
            "item_count >= 0 AND page >= 1", name=op.f("ck_collection_results_counts_valid")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["collection_jobs.id"],
            name=op.f("fk_collection_results_job_id_collection_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reused_result_id"],
            ["collection_results.id"],
            name=op.f("fk_collection_results_reused_result_id_collection_results"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_results")),
    )
    op.create_index(
        "ix_collection_results_cache_key_expires_at",
        "collection_results",
        ["cache_key", "expires_at"],
        unique=False,
    )
    op.create_index("ix_collection_results_job_id", "collection_results", ["job_id"], unique=False)
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("relationship_id", sa.Uuid(), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("collection_result_id", sa.Uuid(), nullable=True),
        sa.Column("observation_kind", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("provider_object_id", sa.String(length=256), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normalized", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=True),
        sa.Column("raw_pointer", sa.String(length=256), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "verification_status",
            sa.String(length=16),
            server_default=sa.text("'unverified'"),
            nullable=False,
        ),
        sa.Column("is_redacted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), nullable=False),
        sa.Column(
            "transformation_history",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_evidence_content_hash_hex")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(transformation_history) = 'array'",
            name=op.f("ck_evidence_history_is_array"),
        ),
        sa.CheckConstraint(
            "raw_sha256 IS NULL OR raw_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_evidence_raw_hex")
        ),
        sa.CheckConstraint(
            "verification_status IN ('unverified', 'corroborated', 'verified', 'disputed')",
            name=op.f("ck_evidence_verification_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_result_id"],
            ["collection_results.id"],
            name=op.f("fk_evidence_collection_result_id_collection_results"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_evidence_entity_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["collection_jobs.id"],
            name=op.f("fk_evidence_job_id_collection_jobs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["evidence_sources.id"],
            name=op.f("fk_evidence_source_id_evidence_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["evidence.id"],
            name=op.f("fk_evidence_supersedes_id_evidence"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
    )
    op.create_index(
        "ix_evidence_collection_result_id", "evidence", ["collection_result_id"], unique=False
    )
    op.create_index(
        "ix_evidence_entity_id_collected_at",
        "evidence",
        ["entity_id", "collected_at"],
        unique=False,
    )
    op.create_index("ix_evidence_job_id", "evidence", ["job_id"], unique=False)
    op.create_index("ix_evidence_source_id", "evidence", ["source_id"], unique=False)
    op.execute(_EVIDENCE_GUARD_FUNCTION)
    for trigger in _EVIDENCE_GUARD_TRIGGERS:
        op.execute(trigger)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS evidence_no_truncate ON evidence")
    op.execute("DROP TRIGGER IF EXISTS evidence_append_only ON evidence")
    op.execute("DROP FUNCTION IF EXISTS omniosint_evidence_guard()")
    op.drop_index("ix_evidence_source_id", table_name="evidence")
    op.drop_index("ix_evidence_job_id", table_name="evidence")
    op.drop_index("ix_evidence_entity_id_collected_at", table_name="evidence")
    op.drop_index("ix_evidence_collection_result_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_collection_results_job_id", table_name="collection_results")
    op.drop_index("ix_collection_results_cache_key_expires_at", table_name="collection_results")
    op.drop_table("collection_results")
    op.drop_index("ix_collection_job_events_job_id_occurred_at", table_name="collection_job_events")
    op.drop_table("collection_job_events")
    op.drop_index("ix_collection_jobs_status", table_name="collection_jobs")
    op.drop_index("ix_collection_jobs_request_id", table_name="collection_jobs")
    op.drop_index(
        "ix_collection_jobs_queue",
        table_name="collection_jobs",
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.drop_index(
        "ix_collection_jobs_leases",
        table_name="collection_jobs",
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_index("ix_collection_jobs_created_at_id", table_name="collection_jobs")
    op.drop_table("collection_jobs")
    op.drop_table("scope_rules")
    op.drop_index("ix_collection_requests_entity_id", table_name="collection_requests")
    op.drop_index("ix_collection_requests_created_by", table_name="collection_requests")
    op.drop_index("ix_collection_requests_created_at_id", table_name="collection_requests")
    op.drop_table("collection_requests")
    op.drop_index("ix_search_history_user_id_created_at", table_name="search_history")
    op.drop_table("search_history")
    op.drop_index("ix_scopes_valid_until", table_name="scopes")
    op.drop_table("scopes")
    op.drop_table("saved_searches")
    op.drop_table("provider_usage")
    op.drop_index("ix_raw_objects_retain_until", table_name="raw_objects")
    op.drop_table("raw_objects")
    op.drop_table("providers")
    op.drop_table("evidence_sources")
    op.drop_index("ix_entities_last_observed_at", table_name="entities")
    op.drop_table("entities")
