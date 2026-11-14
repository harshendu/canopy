import type { PointerEvent as ReactPointerEvent } from "react";
import { PointerSensor, type PointerSensorOptions } from "@dnd-kit/core";

/** The pointer sensor for mouse and pen. Touch is left to the TouchSensor's press-and-hold,
 *  so a swipe across a board still scrolls it (a pointer sensor would claim every touch). */
export class MouseAndPenSensor extends PointerSensor {
  static activators = [
    {
      eventName: "onPointerDown" as const,
      handler: (
        { nativeEvent: event }: ReactPointerEvent,
        { onActivation }: PointerSensorOptions,
      ): boolean => {
        if (event.pointerType === "touch" || !event.isPrimary || event.button !== 0) return false;
        onActivation?.({ event });
        return true;
      },
    },
  ];
}

/** Activation for the board's sensors: a small mouse move, or a press-and-hold on touch. */
export const MOUSE_ACTIVATION = { distance: 6 } as const;
export const TOUCH_ACTIVATION = { delay: 220, tolerance: 6 } as const;
