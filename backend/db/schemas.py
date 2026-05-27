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
