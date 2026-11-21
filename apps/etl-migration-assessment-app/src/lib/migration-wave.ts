export const waveDefinitions = [
  {
    rawValue: "Wave 1",
    label: "Wave 1",
    guidance: "Resolve shared prerequisites and agree source bindings.",
  },
  {
    rawValue: "Pilot",
    label: "Wave 2",
    guidance: "Prove representative transformations and operational controls.",
  },
  {
    rawValue: "Wave 2",
    label: "Wave 3",
    guidance: "Apply reviewed patterns to the remaining backlog.",
  },
  {
    rawValue: "Redesign",
    label: "Wave 4",
    guidance: "Redesign unsupported or specialist workflow semantics.",
  },
] as const;

const labelByRaw = new Map<string, string>(
  waveDefinitions.map((item) => [item.rawValue.toLowerCase(), item.label]),
);

const guidanceByLabel = new Map<string, string>(
  waveDefinitions.map((item) => [item.label.toLowerCase(), item.guidance]),
);

export function waveLabel(value: unknown): string {
  const raw = String(value ?? "").trim();
  if (!raw) return "Unassigned";
  return labelByRaw.get(raw.toLowerCase()) ?? raw;
}

export function waveGuidance(value: unknown): string {
  const normalized = waveLabel(value);
  return (
    guidanceByLabel.get(normalized.toLowerCase()) ??
    "Apply reviewed patterns with measured exit evidence."
  );
}
