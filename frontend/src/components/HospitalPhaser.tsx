import { useEffect, useRef } from "react";
import Phaser from "phaser";

import type { Room, Stage, Role } from "../types";
import { HospitalScene, type HospitalCallbacks } from "../phaser/HospitalScene";

type Props = {
  currentRoom: Room;
  stage: Stage;
  onRoomClick: (room: Room) => void;
  onNpcClick: (role: Role) => void;
  onSceneReady?: (scene: HospitalScene) => void;
};

export function HospitalPhaser({
  currentRoom,
  stage,
  onRoomClick,
  onNpcClick,
  onSceneReady,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<HospitalScene | null>(null);
  const onRoomClickRef = useRef(onRoomClick);
  const onNpcClickRef = useRef(onNpcClick);

  // Keep latest callbacks for the Phaser scene (avoid stale closures).
  useEffect(() => {
    onRoomClickRef.current = onRoomClick;
  }, [onRoomClick]);

  useEffect(() => {
    onNpcClickRef.current = onNpcClick;
  }, [onNpcClick]);

  useEffect(() => {
    if (!containerRef.current) return;

    const callbacks: HospitalCallbacks = {
      onRoomClick: (room: Room) => onRoomClickRef.current(room),
      onNpcClick: (role: Role) => onNpcClickRef.current(role),
    };

    const scene = new HospitalScene(callbacks);
    sceneRef.current = scene;
    onSceneReady?.(scene);

    const game = new Phaser.Game({
      type: Phaser.AUTO,
      parent: containerRef.current,
      width: 900,
      height: 520,
      backgroundColor: "#ffffff",
      scene,
      render: {
        pixelArt: true,
      },
    });

    return () => {
      game.destroy(true);
    };
    // Intentionally only run once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!sceneRef.current) return;
    sceneRef.current.setEncounterUi({ currentRoom, stage });
  }, [currentRoom, stage]);

  return <div ref={containerRef} />;
}

