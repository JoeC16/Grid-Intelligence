import { useState, type ReactNode } from "react";
import { askQuestion, type QueryResult } from "./api";

const EXAMPLES = [
  "Where could a 50 MW data centre connect fastest within 30 km of Slough?",
  "Which substations have the most demand stuck in the queue?",
  "What are the five most constrained primaries in London?",
];

interface Props {
  result: QueryResult | null;
  onResult: (r: QueryResult | null) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
}

// Minimal, safe Markdown: paragraphs, "- " / "1. " lists, **bold**. No HTML injection.
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
  );
}

function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((it, i) => <li key={i}>{inline(it)}</li>);
    blocks.push(
      list.ordered ? (
        <ol key={blocks.length} className="ml-4 list-decimal space-y-1">{items}</ol>
      ) : (
        <ul key={blocks.length} className="ml-4 list-disc space-y-1">{items}</ul>
      ),
    );
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = line.match(/^[-*•]\s+(.*)/);
    const num = line.match(/^\d+[.)]\s+(.*)/);
    if (bullet || num) {
      const ordered = !!num;
      if (!list || list.ordered !== ordered) {
        flush();
        list = { ordered, items: [] };
      }
      list.items.push((bullet ?? num)![1]);
    } else {
      flush();
      if (line) blocks.push(<p key={blocks.length}>{inline(line.replace(/^#+\s*/, ""))}</p>);
    }
  }
  flush();
  return <div className="space-y-2 text-sm leading-relaxed text-stone-800">{blocks}</div>;
}

export default function AskPanel({ result, onResult, selectedId, onSelect, onClose }: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (q: string) => {
    if (q.trim().length < 3 || loading) return;
    setQuestion(q);
    setLoading(true);
    setError(null);
    onResult(null);
    try {
      onResult(await askQuestion(q.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="pointer-events-auto flex max-h-full w-96 max-w-[calc(100vw-1.5rem)] flex-col rounded-md bg-white shadow-lg">
      <div className="flex items-start justify-between border-b border-stone-200 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-stone-900">Ask</p>
          <p className="mt-0.5 text-[11px] leading-snug text-stone-500">
            Answers use only figures looked up in the published data.
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close ask" className="ml-2 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700">
          ✕
        </button>
      </div>

      <form
        className="flex gap-2 px-4 pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit(question);
        }}
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Room for 30 MW near Basildon?"
          aria-label="Question"
          maxLength={500}
          className="min-w-0 flex-1 rounded border border-stone-300 px-2 py-1.5 text-sm text-stone-900 placeholder:text-stone-400"
        />
        <button
          type="submit"
          disabled={loading || question.trim().length < 3}
          className="rounded bg-stone-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
        >
          {loading ? "…" : "Ask"}
        </button>
      </form>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {!result && !loading && !error && (
          <div className="space-y-1.5">
            <p className="text-[11px] text-stone-500">Try:</p>
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" onClick={() => submit(ex)} className="block text-left text-xs text-stone-700 hover:underline">
                {ex}
              </button>
            ))}
          </div>
        )}
        {loading && <p className="text-sm text-stone-500">Looking it up… this can take 20–40 seconds.</p>}
        {error && <p className="text-sm text-red-700">{error}</p>}
        {result && (
          <>
            <Markdown text={result.answer} />
            {result.unverified_numbers.length > 0 && (
              <p className="mt-3 rounded bg-amber-50 p-2 text-[11px] text-amber-900">
                ⚠ Not found in the looked-up data: {result.unverified_numbers.join(", ")}. Treat these figures with care.
              </p>
            )}
            {result.sites.length > 0 && (
              <>
                <p className="mt-4 text-xs font-semibold uppercase tracking-wide text-stone-500">Sites in this answer</p>
                <ol className="mt-1">
                  {result.sites.map((s, i) => (
                    <li key={s.site_id}>
                      <button
                        type="button"
                        onClick={() => onSelect(s.site_id)}
                        className={`flex w-full gap-2 rounded px-1 py-1 text-left text-xs hover:bg-stone-50 ${s.site_id === selectedId ? "bg-stone-100" : ""}`}
                      >
                        <span className="w-4 text-right tabular-nums text-stone-400">{i + 1}</span>
                        <span className="text-stone-900">{s.name}</span>
                      </button>
                    </li>
                  ))}
                </ol>
              </>
            )}
            <p className="mt-4 text-[11px] text-stone-500">
              Looked up: {result.tool_calls.map((c) => c.name).join(", ") || "nothing"}. {result.disclaimer}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
