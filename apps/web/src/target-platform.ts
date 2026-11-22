export type TargetPlatformInfo = {
  platform_id: string;
  display_name: string;
  provider_version: string;
  supported_ir_versions: string[];
  implemented: boolean;
  status: "ready" | "placeholder";
  capabilities: string[];
  description: string;
};

export function isTargetPlatformInfo(value: unknown): value is TargetPlatformInfo {
  if (typeof value !== "object" || value === null) return false;
  const platform = value as Record<string, unknown>;
  return (
    typeof platform.platform_id === "string" &&
    typeof platform.display_name === "string" &&
    typeof platform.provider_version === "string" &&
    Array.isArray(platform.supported_ir_versions) &&
    platform.supported_ir_versions.every((item: unknown) => typeof item === "string") &&
    typeof platform.implemented === "boolean" &&
    (platform.status === "ready" || platform.status === "placeholder") &&
    Array.isArray(platform.capabilities) &&
    platform.capabilities.every((item: unknown) => typeof item === "string") &&
    typeof platform.description === "string"
  );
}

export function parseTargetCatalog(payload: unknown): TargetPlatformInfo[] {
  if (
    typeof payload !== "object" || payload === null || !("targets" in payload) ||
    !Array.isArray(payload.targets) || !payload.targets.every(isTargetPlatformInfo)
  ) {
    throw new Error("Invalid target catalog");
  }
  return payload.targets;
}
