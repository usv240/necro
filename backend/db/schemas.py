"""Pydantic models for NECRO MongoDB documents."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DeathReasonDoc(BaseModel):
    primary_reason: str = ""
    category: str = "unknown"
    specific_constraint: str = ""
    is_temporary: bool = False
    confidence: str = "low"
    cited_evidence: str = ""


class ViabilityDoc(BaseModel):
    is_still_valid: Optional[bool] = None
    what_changed: str = ""
    revival_feasibility: int = 0
    effort_estimate: str = ""
    effort_category: str = "weeks"
    technical_risks: list[str] = []
    recommendation: str = "investigate_further"
    reasoning: str = ""
    confidence: str = "low"


class ROIDoc(BaseModel):
    request_count: int = 0
    demand_level: str = "unknown"
    priority_tier: str = "P3 — Consider"
    roi_estimate_label: str = ""
    competitive_gap: str = ""
    value_drivers: list[str] = []
    reasoning: str = ""
    caveats: str = ""


class CompetitiveIntelDoc(BaseModel):
    competitors_with_feature: list[str] = []
    market_urgency: str = "unknown"   # critical | high | medium | low | unknown
    summary: str = ""
    sources_checked: list[str] = []


class FeatureDoc(BaseModel):
    project_path: str
    scan_id: str
    feature_id: str
    name: str
    kill_commit_sha: str = ""
    kill_commit_message: str = ""
    kill_date: str = ""
    detection_method: str = ""
    linked_mr_iid: Optional[int] = None
    linked_issue_iids: list[int] = []
    context_snippets: list[str] = []
    diff_excerpt: str = ""
    death_reason: DeathReasonDoc = Field(default_factory=DeathReasonDoc)
    viability: ViabilityDoc = Field(default_factory=ViabilityDoc)
    roi: ROIDoc = Field(default_factory=ROIDoc)
    competitive_intel: Optional[CompetitiveIntelDoc] = None
    revival_score: int = 0          # 0-100 composite priority score (40% feasibility + 30% demand + 15% effort + 15% competitive)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def recommendation(self) -> str:
        return self.viability.recommendation


class ScanDoc(BaseModel):
    scan_id: str
    project_path: str
    repo_url: str = ""
    scan_date: datetime = Field(default_factory=datetime.utcnow)
    total_commits_scanned: int = 0
    features_found: int = 0
    revive_now_count: int = 0
    investigate_count: int = 0
    keep_buried_count: int = 0
    status: str = "done"   # running | done | error


class WatchedRepo(BaseModel):
    project_path: str
    repo_url: str = ""
    label: str = ""
    added_at: datetime = Field(default_factory=datetime.utcnow)
    last_scanned: Optional[datetime] = None
    last_scan_id: Optional[str] = None
    revive_now_count: int = 0
    scan_interval_hours: int = 24


class RevivalLogEntry(BaseModel):
    feature_id: str
    feature_name: str
    project_path: str
    issue_url: str = ""
    issue_iid: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    via: str = "gitlab_mcp"


class IssueEmbeddingDoc(BaseModel):
    project_path: str
    issue_iid: int
    title: str = ""
    web_url: str = ""
    embedding: list[float] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RevivalContractDoc(BaseModel):
    """Persisted Feature Will — created at the moment of feature death."""
    contract_id: str
    project_path: str
    mr_iid: int
    mr_title: str
    feature_name: str
    kill_reason: str = ""
    kill_category: str = "unknown"
    is_temporary: bool = False
    revival_condition: str = ""
    revival_effort: str = ""
    demand_signal: str = ""
    confidence: str = "medium"
    author_name: str = ""
    author_gitlab_id: Optional[int] = None
    issue_url: str = ""
    issue_iid: Optional[int] = None
    status: str = "active"   # active | fulfilled | abandoned
    embedding: list[float] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    fulfilled_at: Optional[datetime] = None
    resolved_by: str = ""


class VitalitySnapshot(BaseModel):
    """
    Time-series snapshot of a feature's vitality signals.
    Stored in the 'feature_vitality' MongoDB time-series collection.
    timeField: ts  |  metaField: feature_id
    """
    feature_id: str
    project_path: str
    ts: datetime = Field(default_factory=datetime.utcnow)
    demand_count: int = 0        # open issues matching this feature name
    revival_score: int = 0       # composite 0-100 revival priority score
    days_since_kill: int = 0     # calendar days elapsed since kill_date
    recommendation: str = "unknown"
