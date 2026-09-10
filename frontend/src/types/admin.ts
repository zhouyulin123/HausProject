export type GovernanceCaseSplit =
  | "unassigned"
  | "development"
  | "regression"
  | "blind";

export type GovernanceRedactionReview = "pending" | "reviewed" | "rejected";

export type GovernanceConsentStatus =
  | "pending"
  | "granted"
  | "denied"
  | "revoked"
  | "expired";

export type GovernanceAnnotationStatus = "pending" | "ready";

export interface GovernanceCase {
  case_ref: string;
  origin: "private_real";
  split: GovernanceCaseSplit;
  redaction_review: GovernanceRedactionReview;
  consent_status: GovernanceConsentStatus;
  annotation_status: GovernanceAnnotationStatus;
  record_version: number;
  blockers: string[];
  created_at: string;
  updated_at: string;
}

export interface GovernanceCaseListResponse {
  items: GovernanceCase[];
  total: number;
}

export interface CaseImportPayload {
  client_import_id: string;
  task_id: number;
  uploaded_image_id: number;
}

export interface CaseImportPreview {
  task_input_ready: boolean;
  asset_available: boolean;
  duplicate_asset: boolean;
}

export interface CaseImportResponse {
  created: boolean;
  case: GovernanceCase;
}

export type GovernanceCaseUpdate =
  | {
    expected_version: number;
    split: GovernanceCaseSplit;
  }
  | {
    expected_version: number;
    redaction_review: GovernanceRedactionReview;
  };

export type ConsentDecision = "granted" | "denied" | "revoked";

export type ConsentLegalBasis =
  | "explicit_consent"
  | "contract"
  | "withdrawal_request";

export interface ConsentDecisionPayload {
  expected_version: number;
  decision: ConsentDecision;
  legal_basis: ConsentLegalBasis;
  allowed_purposes: Array<"offline_evaluation">;
  evidence_digest: string;
  effective_at: string;
  expires_at: string | null;
}

export interface AnnotationRevisionPayload {
  expected_version: number;
  annotation: Record<string, unknown>;
}

export interface DatasetFreezePayload {
  dataset_version: string;
  cases: Array<{
    case_ref: string;
    expected_version: number;
  }>;
}

export interface DatasetRevisionResponse {
  revision_ref: string;
  schema_version: "2.0";
  dataset_version: string;
  manifest_digest: string;
  case_count: number;
  split_counts: Record<string, number>;
  created_at: string;
}
