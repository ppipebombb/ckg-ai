"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { SendHorizontal, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { asApiError } from "@/lib/api/client";
import { postChatMessage, type ChatPage } from "@/lib/api/chatbot";

type Bubble = { role: "user" | "assistant"; content: string; error?: boolean };

// Page-aware starter chips (shown only while the conversation is empty).
const STARTERS: Record<ChatPage, string[]> = {
  dashboard: [
    "Apa arti grafik Cascade Hipertensi?",
    "Apa arti 'tertatalaksana'?",
    "Kenapa ada pasien 'tidak berkunjung'?",
  ],
  "dashboard-dm": [
    "Apa arti grafik Diabetes Melitus 2 Tahun Berturut-turut?",
    "Siapa yang dihitung sebagai 'DM murni'?",
    "Apa beda 'Pasien Baru' dan 'Sudah DM'?",
  ],
  patients: [
    "Apa yang ditampilkan halaman Pasien ini?",
    "Apa arti status ASIK Only / EPUS Only / Matched?",
    "Bagaimana cara kerja filter umur?",
  ],
  "school-patients": [
    "Apa yang ditampilkan halaman CKG Sekolah ini?",
    "Apa arti status Belum / Sedang / Selesai Pemeriksaan?",
    "Bagaimana cara filter sekolah dan kelas?",
  ],
  "hipertensi-report": [
    "Kenapa status Hipertensi tapi Riwayat 'Tidak'?",
    "Apa itu Missed Visit?",
    "Bagaimana rumus Interpretasi?",
  ],
  "gap-tatalaksana": [
    "Dari mana angka daftar ini berasal?",
    "Apa arti 'belum tertatalaksana'?",
    "Kenapa ada pasien tanpa no telp?",
  ],
  "dm-report": [
    "Siapa saja yang masuk daftar registri DM ini?",
    "Kenapa kolom Follow Up banyak yang kosong?",
    "Apa bedanya GDS, GDP, dan GD2PP?",
  ],
  "lipid-report": [
    "Siapa saja yang masuk registri Dislipidemia ini?",
    "Kenapa Follow Up hanya dinilai tiap 3 bulan?",
    "Apa bedanya Kolesterol Total, LDL, HDL, dan Trigliserida?",
  ],
  "obesitas-report": [
    "Siapa saja yang masuk registri Obesitas ini?",
    "Bagaimana IMT dihitung di halaman ini?",
    "Kapan target penurunan berat badan dianggap tercapai?",
  ],
  "bayi-kuning-ikterus": [
    "Siapa saja yang masuk registri Bayi Kuning ini?",
    "Apa beda Ikterus dan Ikterus berat?",
    "Apa arti tanda EPUS dan Hitung?",
  ],
  "bayi-kuning-ikterus-berat": [
    "Kapan bayi dinilai Ikterus berat?",
    "Apa arti tanda EPUS dan Hitung?",
    "Dari mana kolom Rujuk Eksternal diambil?",
  ],
  common: ["Dari mana data ini berasal?", "Apa yang bisa kamu jelaskan?"],
};

function pageFromPath(pathname: string): ChatPage {
  // The DM subtab first — /dashboard is a prefix of it.
  if (pathname.startsWith("/dashboard/diabetes-melitus")) return "dashboard-dm";
  if (pathname.startsWith("/dashboard")) return "dashboard";
  // Check /school-patients before /patients (the latter is not a prefix of it,
  // but keep the more specific route first for clarity).
  if (pathname.startsWith("/school-patients")) return "school-patients";
  if (pathname.startsWith("/patients")) return "patients";
  // The sub-page first — /hipertensi-report is a prefix of it.
  if (pathname.startsWith("/hipertensi-report/gap-tatalaksana"))
    return "gap-tatalaksana";
  if (pathname.startsWith("/hipertensi-report")) return "hipertensi-report";
  if (pathname.startsWith("/dm-report")) return "dm-report";
  if (pathname.startsWith("/lipid-report")) return "lipid-report";
  if (pathname.startsWith("/obesitas-report")) return "obesitas-report";
  // The -berat route is a prefix collision with -ikterus; check it first.
  if (pathname.startsWith("/bayi-kuning-ikterus-berat"))
    return "bayi-kuning-ikterus-berat";
  if (pathname.startsWith("/bayi-kuning-ikterus")) return "bayi-kuning-ikterus";
  return "common";
}

// Minimal, dependency-free markdown for chat answers: **bold**, bullet/numbered
// lists, headings, and tables flattened to readable lines (a 2-col table is
// unreadable in a narrow bubble). The system prompt steers the bot toward short
// bullets over tables for casual users; this just renders what arrives nicely.
function renderInline(text: string, k: string): ReactNode[] {
  // Split on ** to toggle bold; an unbalanced ** simply degrades to plain text.
  return text
    .split("**")
    .map((part, i) =>
      i % 2 === 1 ? <strong key={`${k}b${i}`}>{part}</strong> : <span key={`${k}t${i}`}>{part}</span>,
    );
}

function Markdown({ text }: { text: string }) {
  const lines = text.trim().split("\n");
  const out: ReactNode[] = [];
  let para: string[] = [];
  const flush = () => {
    if (!para.length) return;
    const k = `p${out.length}`;
    out.push(
      <p key={k} className="whitespace-pre-wrap">
        {renderInline(para.join("\n"), k)}
      </p>,
    );
    para = [];
  };

  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (l.trim() === "") {
      flush();
      i++;
    } else if (l.includes("|")) {
      // table → flatten consecutive pipe-rows, dropping |---|:--| separators
      flush();
      const rows: string[] = [];
      while (i < lines.length && lines[i].includes("|")) {
        const ln = lines[i];
        if (!/^[\s|:-]+$/.test(ln)) {
          const cells = ln
            .replace(/^\s*\|/, "")
            .replace(/\|\s*$/, "")
            .split("|")
            .map((c) => c.trim())
            .filter(Boolean);
          if (cells.length) rows.push(cells.join(" — "));
        }
        i++;
      }
      const k = `tb${out.length}`;
      out.push(
        <div key={k} className="space-y-1">
          {rows.map((r, ri) => (
            <p key={ri}>{renderInline(r, `${k}-${ri}`)}</p>
          ))}
        </div>,
      );
    } else if (/^\s*[-*]\s+/.test(l)) {
      flush();
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i++;
      }
      const k = `ul${out.length}`;
      out.push(
        <ul key={k} className="list-disc space-y-1 pl-5">
          {items.map((it, ii) => (
            <li key={ii}>{renderInline(it, `${k}-${ii}`)}</li>
          ))}
        </ul>,
      );
    } else if (/^\s*\d+\.\s+/.test(l)) {
      flush();
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i++;
      }
      const k = `ol${out.length}`;
      out.push(
        <ol key={k} className="list-decimal space-y-1 pl-5">
          {items.map((it, ii) => (
            <li key={ii}>{renderInline(it, `${k}-${ii}`)}</li>
          ))}
        </ol>,
      );
    } else if (/^#{1,6}\s+/.test(l)) {
      flush();
      const k = `h${out.length}`;
      out.push(
        <p key={k} className="font-semibold">
          {renderInline(l.replace(/^#{1,6}\s+/, ""), k)}
        </p>,
      );
      i++;
    } else {
      para.push(l);
      i++;
    }
  }
  flush();
  return <div className="space-y-2">{out}</div>;
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1.5 px-4 py-3" aria-label="Mengetik">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="h-2 w-2 animate-bounce rounded-full bg-[var(--muted-foreground)]"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </div>
  );
}

// Flowing "ocean wave" shown in the composer while the AI is thinking. The SVG
// is 200% wide with two wave periods so translateX(-50%) (wave-flow keyframe in
// globals.css) loops seamlessly. Two layered sine paths give it depth.
function ThinkingWave() {
  return (
    <div className="relative h-6 w-full overflow-hidden" aria-label="Asisten sedang berpikir">
      <svg
        className="absolute inset-0 h-full w-[200%] animate-[wave-flow_2.4s_linear_infinite]"
        viewBox="0 0 200 24"
        preserveAspectRatio="none"
        fill="none"
      >
        <defs>
          <linearGradient
            id="ckg-wave"
            x1="0"
            y1="0"
            x2="200"
            y2="0"
            gradientUnits="userSpaceOnUse"
          >
            <stop stopColor="#7c3aed" />
            <stop offset="0.5" stopColor="#4f46e5" />
            <stop offset="1" stopColor="#2563eb" />
          </linearGradient>
        </defs>
        <path
          d="M0 12 Q 12.5 2 25 12 T 50 12 T 75 12 T 100 12 T 125 12 T 150 12 T 175 12 T 200 12"
          stroke="url(#ckg-wave)"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <path
          d="M0 12 Q 12.5 22 25 12 T 50 12 T 75 12 T 100 12 T 125 12 T 150 12 T 175 12 T 200 12"
          stroke="url(#ckg-wave)"
          strokeWidth="1.5"
          strokeLinecap="round"
          opacity="0.4"
        />
      </svg>
    </div>
  );
}

function MessageRow({ bubble }: { bubble: Bubble }) {
  const isUser = bubble.role === "user";
  const isMarkdown = !isUser && !bubble.error;
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3 py-2 text-sm",
          !isMarkdown && "whitespace-pre-wrap",
          isUser
            ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
            : bubble.error
              ? "border border-[var(--destructive)] bg-[var(--background)] text-[var(--destructive)]"
              : "bg-[var(--muted)] leading-relaxed text-[var(--foreground)]",
        )}
      >
        {isMarkdown ? <Markdown text={bubble.content} /> : bubble.content}
      </div>
    </div>
  );
}

export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");

  const pathname = usePathname();
  const page = useMemo(() => pageFromPath(pathname), [pathname]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const mutation = useMutation({
    mutationFn: postChatMessage,
    onSuccess: (res) => {
      setMessages((prev) => [...prev, { role: "assistant", content: res.answer }]);
    },
    onError: (err) => {
      // Chat errors belong in the chat, not a toast. 429 message surfaces verbatim.
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: asApiError(err).message, error: true },
      ]);
    },
  });

  // Auto-scroll to the newest message / thinking indicator.
  useEffect(() => {
    if (open && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, mutation.isPending, open]);

  // Keep the input ready: focus on open and right after a reply lands (the
  // composer remounts when isPending flips back to false), so the user can keep
  // chatting without clicking the field again.
  useEffect(() => {
    if (open && !mutation.isPending) textareaRef.current?.focus();
  }, [open, mutation.isPending]);

  const send = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || mutation.isPending) return;
    // History = only COMPLETED exchanges: a user turn immediately followed by a
    // successful, non-empty assistant reply. Dropping a lone errored turn (its
    // user message + the filtered error bubble) keeps roles strictly
    // alternating. If we instead kept the unanswered user turn, the next request
    // would send two `user` messages in a row — which some OpenAI-compat
    // gateways reject, cascading one transient 429/502 into a permanently broken
    // conversation. Last 20 items (= 10 pairs) — MUST stay in sync with the
    // backend cap in chatbot.py (`max_length` + `history[-20:]`). Content
    // clamped to the backend's 2000-char cap.
    const history: { role: "user" | "assistant"; content: string }[] = [];
    for (let i = 0; i + 1 < messages.length; i++) {
      const u = messages[i];
      const a = messages[i + 1];
      if (u.role === "user" && a.role === "assistant" && !a.error && a.content.trim() !== "") {
        history.push({ role: "user", content: u.content.slice(0, 2000) });
        history.push({ role: "assistant", content: a.content.slice(0, 2000) });
        i++;
      }
    }
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setInput("");
    mutation.mutate({ message: trimmed, page, history: history.slice(-20) });
  };

  return (
    <>
      {/* Panel */}
      <div
        aria-hidden={!open}
        className={cn(
          "fixed z-50 flex origin-bottom-right flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--card-foreground)] shadow-xl transition duration-200",
          "inset-x-4 bottom-24 h-[min(520px,70vh)] sm:inset-x-auto sm:right-6 sm:w-[380px] sm:h-[520px]",
          open
            ? "scale-100 opacity-100"
            : "pointer-events-none scale-95 opacity-0",
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-600 via-indigo-600 to-blue-600 text-white shadow-sm shadow-indigo-600/30">
              <Sparkles className="h-4 w-4" />
            </span>
            <p className="text-sm font-semibold">Asisten CKG</p>
          </div>
          <button
            onClick={() => setOpen(false)}
            aria-label="Tutup"
            className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
          {messages.length === 0 && !mutation.isPending && (
            <div className="space-y-3">
              <p className="text-sm text-[var(--muted-foreground)]">
                Halo! Saya menjelaskan angka dan istilah di dashboard ini. Coba
                tanyakan:
              </p>
              <div className="flex flex-wrap gap-2">
                {STARTERS[page].map((q) => (
                  <button
                    key={q}
                    onClick={() => send(q)}
                    className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-left text-xs hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <MessageRow key={i} bubble={m} />
          ))}

          {mutation.isPending && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-[var(--muted)]">
                <ThinkingDots />
              </div>
            </div>
          )}
        </div>

        {/* Composer — crossfades to a flowing wave while the AI is thinking.
            Both layers stay mounted (the textarea keeps focus across the swap,
            so the user can keep typing without re-clicking). */}
        <div className="relative border-t border-[var(--border)] p-3">
          {/* Wave overlay (visible only while thinking) */}
          <div
            aria-hidden={!mutation.isPending}
            className={cn(
              "pointer-events-none absolute inset-0 flex items-center px-3 transition-opacity duration-300",
              mutation.isPending ? "opacity-100" : "opacity-0",
            )}
          >
            <ThinkingWave />
          </div>
          {/* Input (fades out while thinking) */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className={cn(
              "flex items-end gap-2 transition-opacity duration-300",
              mutation.isPending ? "pointer-events-none opacity-0" : "opacity-100",
            )}
          >
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={1}
              maxLength={1000}
              placeholder="Tulis pertanyaan…"
              className="max-h-28 min-h-9 flex-1 resize-none rounded-md border border-[var(--input)] bg-[var(--background)] px-3 py-2 text-sm placeholder:text-[var(--muted-foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            />
            <button
              type="submit"
              aria-label="Kirim"
              disabled={!input.trim()}
              className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-violet-600 to-indigo-600 text-white transition hover:opacity-90 disabled:pointer-events-none disabled:opacity-40"
            >
              <SendHorizontal className="h-4 w-4" />
            </button>
          </form>
        </div>
      </div>

      {/* Floating AI toggle button */}
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Tutup asisten AI" : "Buka asisten AI"}
        className="group fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-violet-600 via-indigo-600 to-blue-600 text-white shadow-lg shadow-indigo-600/40 transition-transform duration-200 hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:ring-offset-2"
      >
        {/* soft pulsing glow halo */}
        <span
          aria-hidden
          className="absolute inset-0 -z-10 animate-pulse rounded-full bg-gradient-to-br from-violet-500 to-blue-500 opacity-70 blur-lg"
        />
        {/* gentle attention ring while closed */}
        {!open && (
          <span
            aria-hidden
            className="absolute inset-0 animate-ping rounded-full ring-1 ring-white/40 [animation-duration:2.5s]"
          />
        )}
        {open ? (
          <X className="h-6 w-6" />
        ) : (
          <Sparkles className="h-6 w-6 transition-transform duration-200 group-hover:rotate-12 group-hover:scale-110" />
        )}
      </button>
    </>
  );
}
