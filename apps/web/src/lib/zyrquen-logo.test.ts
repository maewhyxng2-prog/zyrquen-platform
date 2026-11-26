import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { COGNITIVE_STATE_EVENT } from "../components/ZyrquenLogo";

const WEB_ROOT = path.resolve(__dirname, "../..");

describe("ZYRQUEN Ω∞ Cognitive Core animated logo & processing detection", () => {
  it("provides animated zyrquen-logo.svg and zyrquen-icon.svg with Orbit and Breathe keyframes", () => {
    const logoSvg = readFileSync(
      path.join(WEB_ROOT, "public", "zyrquen-logo.svg"),
      "utf-8",
    );
    const iconSvg = readFileSync(
      path.join(WEB_ROOT, "public", "zyrquen-icon.svg"),
      "utf-8",
    );

    expect(logoSvg).toContain("ZYRQUEN Ω∞");
    expect(logoSvg).toContain("zq-orbit-outer");
    expect(logoSvg).toContain("zq-core-breathe");
    expect(logoSvg).toContain("@keyframes zq-orbit-cw");
    expect(logoSvg).toContain("@keyframes zq-breathe");
    expect(logoSvg).toContain("prefers-reduced-motion: reduce");

    expect(iconSvg).toContain("zq-orbit-outer");
    expect(iconSvg).toContain("zq-core-breathe");
  });

  it("defines accelerated Orbit and Breathe durations in globals.css during processing state", () => {
    const css = readFileSync(
      path.join(WEB_ROOT, "src", "app", "globals.css"),
      "utf-8",
    );

    expect(css).toContain(".zq-logo .zq-orbit-outer");
    expect(css).toContain("animation: zq-orbit-cw 24s linear infinite");
    expect(css).toContain(".zq-logo .zq-core-breathe");
    expect(css).toContain("animation: zq-core-breathe 4.2s ease-in-out infinite");
    expect(css).toContain(".zq-logo-processing .zq-orbit-outer");
    expect(css).toContain("animation-duration: 3.2s");
    expect(css).toContain(".zq-logo-processing .zq-core-breathe");
    expect(css).toContain("animation-duration: 1.15s");
  });

  it("wires cognitive processing state detection between WorkspaceClient and AppShell", () => {
    const appShell = readFileSync(
      path.join(WEB_ROOT, "src", "components", "AppShell.tsx"),
      "utf-8",
    );
    const workspace = readFileSync(
      path.join(WEB_ROOT, "src", "components", "WorkspaceClient.tsx"),
      "utf-8",
    );

    expect(COGNITIVE_STATE_EVENT).toBe("zyrquen:cognitive-state");
    expect(appShell).toContain("COGNITIVE_STATE_EVENT");
    expect(appShell).toContain("isCognitiveProcessing");
    expect(appShell).toContain('data-cognitive-state={isCognitiveProcessing ? "processing" : "idle"}');
    expect(workspace).toContain("emitCognitiveState(Boolean(requestPhase), requestPhase)");
  });
});
