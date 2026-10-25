/** 与后端 API 严格对应的数据类型。 */

export interface DialogColumn {
  key: string;
  label: string;
  mono?: boolean;
  align?: "left" | "right";
  width?: string;
  wrap?: boolean;
}

export type DialogCell = string | number | null | undefined;
export type DialogRow = Record<string, DialogCell>;

export interface FileInfo {
  name: string;
  size: number;
  sheet: string;
}

export interface ColumnNames {
  code: string;
  name: string;
  system: string;
  profession: string;
}

export interface CategoryEntry {
  row: number | string;
  code: string;
  name: string;
  system: string;
  excluded: boolean;
}

export interface CategorySystem {
  system: string;
  count: number;
}

export interface CategoryGroup {
  profession: string;
  system: string;
  systems: CategorySystem[];
  count: number;
  trainable_count: number;
  excluded_count: number;
  entries: CategoryEntry[];
}

export interface ConflictDetail {
  row: number | string;
  profession: string;
  system: string;
}

export interface ConflictGroup {
  code: string;
  name: string;
  count: number;
  rows: Array<number | string>;
  professions: string[];
  systems: string[];
  detail: ConflictDetail[];
}

export interface DuplicateGroup {
  code: string;
  name: string;
  profession: string;
  system: string;
  count: number;
  rows: Array<number | string>;
}

export interface SameNameDiffCode {
  name: string;
  codes: string[];
  count: number;
  rows: Array<number | string>;
  professions: string[];
  systems: string[];
  same_profession: boolean;
  severity: "info" | "warning";
}

export interface SameCodeDiffName {
  code: string;
  names: string[];
  count: number;
  rows: Array<number | string>;
  professions: string[];
  systems: string[];
  same_profession: boolean;
  severity: "info" | "warning";
}

export interface ProfessionMultiSystem {
  profession: string;
  systems: CategorySystem[];
}

export interface MissingField {
  count: number;
  rows: Array<number | string>;
}

export interface ReferenceQuality {
  conflicts: ConflictGroup[];
  conflict_group_count: number;
  conflict_row_count: number;
  duplicates: DuplicateGroup[];
  same_name_different_code: SameNameDiffCode[];
  same_code_different_name: SameCodeDiffName[];
  profession_multiple_systems: ProfessionMultiSystem[];
  missing: {
    name: MissingField;
    profession: MissingField;
    system: MissingField;
    code: MissingField;
  };
}

export interface ReferenceAnalysis {
  reference_id: string;
  file: FileInfo;
  columns: ColumnNames;
  raw_rows: number;
  usable_rows: number;
  training_rows: number;
  excluded_rows: number;
  training_category_count: number;
  categories: CategoryGroup[];
  quality: ReferenceQuality;
}

export interface PendingReport {
  type: string;
  code: string;
  name: string;
  count: number;
  detail: string;
  action: string;
}

export type PendingStatus = "auto" | "manual";

export interface PendingItem {
  index: number;
  code: string;
  name: string;
  units: string[];
  unit_counts: Record<string, number>;
  count: number;
  source_rows: Array<number | string>;
  status: PendingStatus;
  reason: string;
  needs_confirmation: boolean;
}

export interface PendingPreview {
  index: number;
  code: string;
  name: string;
  units: string[];
  count: number;
  status: PendingStatus;
  reason: string;
  needs_confirmation: boolean;
}

export interface PendingAnalysis {
  pending_id: string;
  file: FileInfo & { header_row: number };
  columns: {
    code: string;
    name: string;
    unit: string;
  };
  raw_rows: number;
  unique_rows: number;
  group_count: number;
  auto_count: number;
  manual_count: number;
  multi_unit_count: number;
  exact_duplicate_rows: number;
  duplicate_rows: number;
  dedup_basis: string;
  missing_name_count: number;
  missing_name_rows: Array<number | string>;
  reports: PendingReport[];
  items: PendingItem[];
  preview: PendingPreview[];
}

export interface ResultRow {
  index: number;
  code: string;
  name: string;
  system: string;
  profession: string;
  confidence: number;
  low_confidence: boolean;
  duplicate_count: number;
  source_rows: Array<number | string>;
  units: string[];
  status: PendingStatus;
  reason: string;
  needs_confirmation: boolean;
}

export interface ClassifyCategory {
  profession: string;
  system: string;
}

export interface ClassifySummary {
  raw_rows: number;
  unique_rows: number;
  group_count: number;
  auto_count: number;
  manual_count: number;
  multi_unit_count: number;
  low_confidence_count: number;
  threshold: number;
  dedup_basis: string;
}

export interface ClassifyResponse {
  task_id: string;
  rows: ResultRow[];
  auto_rows: ResultRow[];
  manual_rows: ResultRow[];
  categories: ClassifyCategory[];
  columns: ColumnNames;
  summary: ClassifySummary;
  stats: {
    professions: Record<string, number>;
    systems: Record<string, number>;
    total: number;
  };
  conflicts: ConflictGroup[];
  mapping: Record<string, unknown>;
  warnings: string[];
  dedup_reports: PendingReport[];
}

export interface ExportResponse {
  path: string;
  download_url: string;
  filename: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  categories?: string[];
}
