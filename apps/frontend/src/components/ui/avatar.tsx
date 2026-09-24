"use client";

// #521 (spec #520 "One shared avatar primitive"): the shared circular avatar
// with the precedence chain photo_ref -> first letter of name -> person icon.
// One component serves the desktop patient account trigger (#521), the More
// account card (#525), and the dropdown identity header (#526) - consumers
// size it via className and never fork the chain. Initials are taken by code
// point so Devanagari names (and astral-plane characters) render their first
// letter intact.
//
// The photo branch is dormant until the photo-upload seam lands: `photo_ref`
// today holds only the client-side file name the wizard records (no URL
// resolver exists), and a bare name must not render as a broken image. The
// branch stays first in the chain and activates the moment a resolvable
// reference exists - the later seam simply produces one.

import type { HTMLAttributes } from "react";

import { User } from "lucide-react";

import { cn } from "@/lib/utils";

export interface AvatarProps extends HTMLAttributes<HTMLSpanElement> {
  photoRef?: string | null;
  name?: string | null;
}

function initialOf(name: string | null | undefined): string | null {
  const trimmed = name?.trim() ?? "";
  if (!trimmed) return null;
  return Array.from(trimmed)[0] ?? null;
}

/**
 * Whether a photo reference is displayable today. A bare file name (all the
 * profile seam carries pre-upload) has no src; treat it as dormant/unset so
 * it falls through to the name initial instead of a broken image.
 */
function isResolvablePhotoRef(photoRef: string | null | undefined): boolean {
  if (!photoRef) return false;
  return (
    photoRef.startsWith("http://") ||
    photoRef.startsWith("https://") ||
    photoRef.startsWith("/") ||
    photoRef.startsWith("data:") ||
    photoRef.startsWith("blob:")
  );
}

export function Avatar({ photoRef, name, className, ...rest }: AvatarProps) {
  const photo = isResolvablePhotoRef(photoRef) ? photoRef : null;
  const initial = initialOf(name);

  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex items-center justify-center overflow-hidden rounded-full",
        className,
      )}
      {...rest}
    >
      {photo ? (
        <img src={photo} alt="" className="h-full w-full object-cover" />
      ) : initial ? (
        initial
      ) : (
        <User className="h-1/2 w-1/2" />
      )}
    </span>
  );
}
