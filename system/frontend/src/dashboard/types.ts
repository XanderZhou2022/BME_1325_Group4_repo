export type JsonObj = Record<string, unknown>;

export type Admission = {
  admission_id: string;
  encounter_id: string;
  patient_id: string;
  bed_id: string;
  admission_code: string;
  status: "active" | "discharged" | "expired" | "transferred";
  encounter_status: string;
  admit_time: string;
  discharge_time?: string | null;
  primary_diagnosis?: string;
  admission_reason?: string;
  severity_on_admission?: string;
};

export type TablePreview = {
  table_name: string;
  total_rows: number;
  rows: JsonObj[];
};
