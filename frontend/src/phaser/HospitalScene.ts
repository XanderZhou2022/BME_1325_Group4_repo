import Phaser from "phaser";

import type { Room, Stage, Role } from "../types";

export type HospitalCallbacks = {
  onRoomClick: (room: Room) => void;
  onNpcClick: (role: Role) => void;
};

type RoomLayout = {
  centerX: number;
  centerY: number;
  width: number;
  height: number;
  label: string;
};

const ROOM_LAYOUT: Record<Room, RoomLayout> = {
  lobby: { centerX: 200, centerY: 110, width: 240, height: 140, label: "大厅" },
  triage_room: {
    centerX: 520,
    centerY: 110,
    width: 240,
    height: 140,
    label: "分诊室",
  },
  doctor_room: {
    centerX: 220,
    centerY: 310,
    width: 520,
    height: 170,
    label: "医生诊室",
  },
  pharmacy_room: {
    centerX: 620,
    centerY: 330,
    width: 320,
    height: 160,
    label: "药房",
  },
};

function requiredRoomForStage(stage: Stage): Room | null {
  if (stage === "triage") return "triage_room";
  if (stage === "consultation") return "doctor_room";
  if (stage === "pharmacy") return "pharmacy_room";
  return null;
}

export class HospitalScene extends Phaser.Scene {
  private callbacks: HospitalCallbacks;
  private currentRoom: Room = "lobby";
  private currentStage: Stage = "triage";

  private patient!: Phaser.GameObjects.Arc;
  private rooms: Record<
    Room,
    {
      rect: Phaser.GameObjects.Rectangle;
      zone: Phaser.GameObjects.Zone;
      labelText: Phaser.GameObjects.Text;
    }
  >;

  private npcButtons: Partial<Record<Role, Phaser.GameObjects.Zone>> = {};

  constructor(callbacks: HospitalCallbacks) {
    super({ key: "HospitalScene" });
    this.callbacks = callbacks;
    this.rooms = {} as any;
  }

  create() {
    const bg = this.add.rectangle(450, 290, 900, 520, 0xffffff, 1);
    bg.setStrokeStyle(2, 0xd0d0d0);

    // Draw rooms.
    (Object.keys(ROOM_LAYOUT) as Room[]).forEach((room) => {
      const layout = ROOM_LAYOUT[room];
      const rect = this.add.rectangle(
        layout.centerX,
        layout.centerY,
        layout.width,
        layout.height,
        0xf4f5f7,
        1,
      );
      rect.setStrokeStyle(2, 0xc7c9d1);
      // Make the visible room rect clickable as well (more robust than only using Zone).
      rect.setInteractive({ useHandCursor: true });

      const zone = this.add
        .zone(layout.centerX, layout.centerY, layout.width, layout.height)
        .setInteractive({ useHandCursor: true });

      const labelText = this.add
        .text(layout.centerX, layout.centerY, layout.label, {
          fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
          fontSize: "16px",
          color: "#111827",
        })
        .setOrigin(0.5, 0.5);

      const onRoomPointerDown = () => this.callbacks.onRoomClick(room);
      rect.on("pointerdown", onRoomPointerDown);
      zone.on("pointerdown", onRoomPointerDown);

      this.rooms[room] = { rect, zone, labelText };
    });

    // Patient marker.
    const lobby = ROOM_LAYOUT.lobby;
    this.patient = this.add.circle(lobby.centerX, lobby.centerY, 12, 0x2563eb);
    this.patient.setStrokeStyle(2, 0x0b3a91);

    // NPC buttons (clickable).
    const nurse = ROOM_LAYOUT.triage_room;
    this.createNpcZone(nurse.centerX + 70, nurse.centerY + 20, "nurse");

    const doctor = ROOM_LAYOUT.doctor_room;
    this.createNpcZone(doctor.centerX + doctor.width / 2 - 70, doctor.centerY, "doctor");

    const pharmacist = ROOM_LAYOUT.pharmacy_room;
    this.createNpcZone(
      pharmacist.centerX + pharmacist.width / 2 - 70,
      pharmacist.centerY - pharmacist.height / 2 + 30,
      "pharmacist",
    );

    this.setEncounterUi({ currentRoom: this.currentRoom, stage: this.currentStage });

    this.bindKeyboardControls();
  }

  private bindKeyboardControls() {
    // Minimal keyboard mapping for demo convenience.
    // You can move patient between areas without clicking.
    const keyboard = this.input.keyboard;
    if (!keyboard) return;

    keyboard.on("keydown-UP", () => this.callbacks.onRoomClick("triage_room"));
    keyboard.on("keydown-LEFT", () => this.callbacks.onRoomClick("lobby"));
    keyboard.on("keydown-RIGHT", () => this.callbacks.onRoomClick("doctor_room"));
    keyboard.on("keydown-DOWN", () => this.callbacks.onRoomClick("pharmacy_room"));
  }

  private createNpcZone(x: number, y: number, role: Role) {
    const zone = this.add
      .zone(x, y, 80, 45)
      .setInteractive({ useHandCursor: true });

    this.add
      .text(x, y, this.npcLabel(role), {
        fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        fontSize: "14px",
        color: "#111827",
      })
      .setOrigin(0.5, 0.5);

    // Little background for readability.
    const pill = this.add.rectangle(x, y, 70, 34, 0xe5e7eb, 0.95);
    pill.setStrokeStyle(1, 0xcbd5e1);

    zone.on("pointerdown", () => {
      // Forward NPC click to React; React can decide whether chat is allowed.
      this.callbacks.onNpcClick(role);
    });

    this.npcButtons[role] = zone;
  }

  private npcLabel(role: Role): string {
    if (role === "nurse") return "护士";
    if (role === "doctor") return "医生";
    if (role === "pharmacist") return "药师";
    return role;
  }

  public setEncounterUi(input: { currentRoom: Room; stage: Stage }) {
    this.currentRoom = input.currentRoom;
    this.currentStage = input.stage;

    const required = requiredRoomForStage(this.currentStage);

    (Object.keys(this.rooms) as Room[]).forEach((room) => {
      const entry = this.rooms[room];
      if (room === this.currentRoom) {
        entry.rect.setFillStyle(0xa7f3d0, 1);
        entry.rect.setStrokeStyle(3, 0x047857);
      } else if (required && room === required) {
        entry.rect.setFillStyle(0x93c5fd, 0.95);
        entry.rect.setStrokeStyle(3, 0x1d4ed8);
      } else {
        entry.rect.setFillStyle(0xf4f5f7, 1);
        entry.rect.setStrokeStyle(2, 0xc7c9d1);
      }
    });
  }

  public goToRoom(room: Room) {
    const layout = ROOM_LAYOUT[room];
    if (!layout) return;
    if (!this.patient) return;

    this.tweens.add({
      targets: this.patient,
      x: layout.centerX,
      y: layout.centerY,
      duration: 700,
      ease: "Power2",
    });
  }
}

