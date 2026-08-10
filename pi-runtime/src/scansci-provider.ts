import type {
  Api,
  AssistantMessageEventStream,
  Context,
  Model,
  SimpleStreamOptions,
} from "@earendil-works/pi-ai";
import { streamSimple as streamAnthropic } from "@earendil-works/pi-ai/api/anthropic-messages";
import { streamSimple as streamOpenAICompletions } from "@earendil-works/pi-ai/api/openai-completions";
import { streamSimple as streamOpenAIResponses } from "@earendil-works/pi-ai/api/openai-responses";
import {
  estimatePiImageTokens,
  validatePiImages,
  type ModelRuntimeDescriptor,
  type PiImageContent,
} from "./multimodal.js";

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function dataUri(value: unknown): { mimeType: string; data: string } | undefined {
  if (typeof value !== "string") return undefined;
  const match = /^data:(image\/[A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)$/.exec(value);
  return match ? { mimeType: match[1].toLowerCase(), data: match[2] } : undefined;
}

function providerImage(value: JsonRecord): { mimeType: string; data: string } | undefined {
  if (value.type === "image_url" && isRecord(value.image_url)) return dataUri(value.image_url.url);
  if (value.type === "input_image") return dataUri(value.image_url);
  if (value.type === "image" && isRecord(value.source) && value.source.type === "base64") {
    if (typeof value.source.media_type !== "string" || typeof value.source.data !== "string") return undefined;
    return { mimeType: value.source.media_type.toLowerCase(), data: value.source.data };
  }
  return undefined;
}

function safeProviderPayload(value: unknown, images: PiImageContent[], depth = 0): unknown {
  if (depth > 40) throw new Error("Provider payload nesting exceeds the safe limit");
  if (Array.isArray(value)) return value.map((item) => safeProviderPayload(item, images, depth + 1));
  if (!isRecord(value)) return value;
  const image = providerImage(value);
  if (image) {
    images.push({
      type: "image",
      data: image.data,
      mimeType: image.mimeType as PiImageContent["mimeType"],
    });
    return {
      type: String(value.type),
      mime_type: image.mimeType,
      decoded_bytes: Buffer.byteLength(image.data, "base64"),
      data: "[VALIDATED IMAGE]",
    };
  }
  const type = String(value.type || "").toLowerCase();
  if (type.includes("image") || "image_url" in value || "source" in value && isRecord(value.source) && value.source.type === "base64") {
    throw new Error("Provider payload contains an unsupported image shape");
  }
  const output: JsonRecord = {};
  for (const [key, item] of Object.entries(value)) output[key] = safeProviderPayload(item, images, depth + 1);
  return output;
}

function conservativeTokens(value: unknown, descriptor: ModelRuntimeDescriptor): number {
  const images: PiImageContent[] = [];
  const text = JSON.stringify(safeProviderPayload(value, images));
  validatePiImages(images);
  if (images.length && !descriptor.input_modalities.includes("image")) {
    throw new Error("Provider payload contains images for a text-only model descriptor");
  }
  let ascii = 0;
  let nonAsciiBytes = 0;
  for (const character of text) {
    if (character.charCodeAt(0) <= 0x7f) ascii += 1;
    else nonAsciiBytes += Buffer.byteLength(character, "utf8");
  }
  return Math.ceil(ascii / 4) + Math.ceil(nonAsciiBytes / 2) + estimatePiImageTokens(images);
}

export function assertProviderRequest(
  payload: unknown,
  descriptor: ModelRuntimeDescriptor,
  api: Api,
): void {
  if (!isRecord(payload)) throw new Error("Provider payload must be an object");
  if (api === "openai-completions" || api === "anthropic-messages") {
    if (!Array.isArray(payload.messages)) throw new Error("Provider payload is missing messages");
  } else if (api === "openai-responses") {
    if (!Array.isArray(payload.input)) throw new Error("Provider payload is missing Responses input");
  } else {
    throw new Error(`Unsupported ScanSci provider API: ${String(api)}`);
  }
  if (payload.model !== descriptor.model_id) {
    throw new Error("Provider payload model does not match the trusted runtime descriptor");
  }
  const outputFields = ["max_tokens", "max_completion_tokens", "max_output_tokens"] as const;
  const presentOutputFields = outputFields.filter((field) => payload[field] !== undefined);
  const allowedOutputFields = api === "openai-responses"
    ? new Set(["max_output_tokens"])
    : api === "anthropic-messages"
      ? new Set(["max_tokens"])
      : new Set(["max_tokens", "max_completion_tokens"]);
  if (
    presentOutputFields.length !== 1
    || !allowedOutputFields.has(presentOutputFields[0])
  ) {
    throw new Error("Provider payload is missing its bounded output budget");
  }
  const requestedOutput = payload[presentOutputFields[0]];
  if (
    requestedOutput !== undefined
    && (typeof requestedOutput !== "number"
      || !Number.isSafeInteger(requestedOutput)
      || requestedOutput < 1
      || requestedOutput > descriptor.max_output_tokens)
  ) {
    throw new Error("Provider payload output budget exceeds the trusted runtime descriptor");
  }
  const estimatedTokens = conservativeTokens(payload, descriptor);
  if (estimatedTokens > descriptor.provider_input_tokens) {
    throw new Error(
      `Provider input budget exceeded before network request: estimated ${estimatedTokens} tokens `
      + `(limit ${descriptor.provider_input_tokens}). Compact the session before retrying.`,
    );
  }
}

export function scansciStreamSimple(descriptor: ModelRuntimeDescriptor) {
  return (
    model: Model<Api>,
    context: Context,
    options?: SimpleStreamOptions,
  ): AssistantMessageEventStream => {
    const originalOnPayload = options?.onPayload;
    const guardedOptions: SimpleStreamOptions = {
      ...options,
      maxTokens: Math.min(
        descriptor.max_output_tokens,
        Number(options?.maxTokens || descriptor.max_output_tokens),
      ),
      onPayload: async (payload, finalModel) => {
        const projected = await originalOnPayload?.(payload, finalModel);
        const finalPayload = projected === undefined ? payload : projected;
        // This check is deliberately below extension hooks. The Pi extension
        // runner catches hook exceptions, but an exception here aborts before
        // the provider SDK's HTTP create() call.
        assertProviderRequest(finalPayload, descriptor, finalModel.api);
        return finalPayload;
      },
    };
    if (model.api === "openai-completions") {
      return streamOpenAICompletions(model, context, guardedOptions);
    }
    if (model.api === "openai-responses") {
      return streamOpenAIResponses(model, context, guardedOptions);
    }
    if (model.api === "anthropic-messages") {
      return streamAnthropic(model, context, guardedOptions);
    }
    throw new Error(`Unsupported ScanSci provider API: ${String(model.api)}`);
  };
}
