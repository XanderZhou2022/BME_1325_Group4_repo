export type Stage = "triage" | "consultation" | "pharmacy" | "completed";
export type Room = "lobby" | "triage_room" | "doctor_room" | "pharmacy_room";
export type Status = "in_progress" | "completed";

export type Role = "system" | "patient" | "nurse" | "doctor" | "pharmacist";

export interface Message {
  id: string;
  role: Role;
  content: string;
  created_at: string;
}

export interface ClinicalState {
  chief_complaint: string;
  lab_results: string[];
  initial_diagnosis: string | null;
  prescription: string | null;
}

export interface PatientMemory {
  name: string;
  age: number;
  gender: string;
  chief_complaint: string;
  assigned_department: string;
}

export interface Encounter {
  id: string;
  status: Status;
  stage: Stage;
  current_room: Room;
  assigned_department: string;
  patient: PatientMemory;
  clinical: ClinicalState;
  stage_message_offset: number;
}

export interface EncounterWithMessages {
  encounter: Encounter;
  messages: Message[];
  can_interact: boolean;
}

