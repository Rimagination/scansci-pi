import { countTokens as countCl100kTokens } from "gpt-tokenizer/encoding/cl100k_base";
import { countTokens as countO200kTokens } from "gpt-tokenizer/encoding/o200k_base";

export interface TokenizerIdentity {
  provider_id: string;
  model_id: string;
}

type KnownEncoding = "cl100k_base" | "o200k_base";
const TOKENIZER_CHUNK_CHARACTERS = 2048;

function knownOpenAIEncoding(descriptor?: TokenizerIdentity): KnownEncoding | undefined {
  if (String(descriptor?.provider_id || "").toLowerCase() !== "openai") return undefined;
  const model = String(descriptor?.model_id || "").toLowerCase();
  if (/^(?:gpt-5|gpt-4o|gpt-4\.1|chatgpt-4o|o[1345](?:-|$))/.test(model)) return "o200k_base";
  if (/^(?:gpt-4(?:-|$)|gpt-3\.5(?:-|$)|text-embedding-)/.test(model)) return "cl100k_base";
  return undefined;
}

/**
 * Count text without relying on unsafe average-characters-per-token ratios.
 *
 * OpenAI models with a declared, known tokenizer use their exact local BPE.
 * Unknown/custom/Anthropic models fall back to UTF-8 bytes: byte-backed
 * tokenizers can always represent each byte with at most one token, making
 * this a provider-neutral upper bound rather than a billing estimate.
 */
export function conservativeTextTokens(text: string, descriptor?: TokenizerIdentity): number {
  if (!text) return 0;
  const encoding = knownOpenAIEncoding(descriptor);
  try {
    const count = encoding === "o200k_base"
      ? countO200kTokens
      : encoding === "cl100k_base"
        ? countCl100kTokens
        : undefined;
    if (count) {
      // BPE merges never cross a chunk boundary, so summing independently
      // encoded chunks is equal to or slightly above the whole-text count.
      // Bounded chunks also avoid quadratic behavior on huge repeated runs.
      let total = 0;
      let start = 0;
      while (start < text.length) {
        let end = Math.min(text.length, start + TOKENIZER_CHUNK_CHARACTERS);
        if (
          end < text.length
          && end > start
          && text.charCodeAt(end - 1) >= 0xD800
          && text.charCodeAt(end - 1) <= 0xDBFF
          && text.charCodeAt(end) >= 0xDC00
          && text.charCodeAt(end) <= 0xDFFF
        ) {
          end -= 1;
        }
        total += count(text.slice(start, end));
        start = end;
      }
      return total;
    }
  } catch {
    // A malformed/special-token payload must become more conservative, never
    // bypass the provider gate because an optional exact tokenizer rejected it.
  }
  return Buffer.byteLength(text, "utf8");
}
