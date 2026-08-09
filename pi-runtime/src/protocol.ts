export const PI_PROTOCOL_VERSION = 4;

export const PI_PROTOCOL_FEATURES = [
  "multi_session",
  "task_contracts",
  "bounded_autonomy",
  "ask_user",
  "plan_approval",
  "follow_up",
  "structured_recovery",
  "session_fork",
  "task_contract_v2",
  "explicit_empty_leases",
  "host_tool_authorization",
  "structured_mcp_effects",
  "current_request_context",
] as const;

type ProtocolRecord = Record<string, unknown>;

export interface ProtocolNegotiation {
  ok: boolean;
  protocol: number;
  missingFeatures: string[];
  error?: string;
}

export function negotiateProtocol(message: ProtocolRecord): ProtocolNegotiation {
  const protocol = Number(message.pi_protocol_version || 0);
  const required = Array.isArray(message.required_features)
    ? [...new Set(message.required_features.map(String).filter(Boolean))]
    : [];
  const supported = new Set<string>(PI_PROTOCOL_FEATURES);
  const missingFeatures = required.filter((feature) => !supported.has(feature));
  if (protocol !== PI_PROTOCOL_VERSION) {
    return {
      ok: false,
      protocol,
      missingFeatures,
      error: `Pi protocol ${protocol || "missing"} is incompatible; version ${PI_PROTOCOL_VERSION} is required.`,
    };
  }
  if (missingFeatures.length) {
    return {
      ok: false,
      protocol,
      missingFeatures,
      error: `Pi runtime is missing required features: ${missingFeatures.join(", ")}.`,
    };
  }
  return { ok: true, protocol, missingFeatures: [] };
}
