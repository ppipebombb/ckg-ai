import { z } from "zod";

// Approximate progress of a background report warm, attached to a `computing`
// response so the UI can render a determinate bar instead of a bare spinner.
// `done`/`total` count patients (distinct NIKs) decrypted so far — an
// approximation (the DB fetch + final aggregate aren't counted).
export const WarmProgressSchema = z.object({
  phase: z.string().default("decrypting"),
  done: z.number().int().default(0),
  total: z.number().int().default(0),
});
export type WarmProgress = z.infer<typeof WarmProgressSchema>;
