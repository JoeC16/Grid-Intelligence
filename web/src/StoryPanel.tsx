import { Markdown } from "./AskPanel";
import type { StoryChapter } from "./api";

interface Props {
  chapters: StoryChapter[] | null;
  index: number;
  onIndex: (i: number) => void;
  error: string | null;
  onClose: () => void;
}

const fmt = (v: number) => v.toLocaleString("en-GB", { maximumFractionDigits: 1 });

export default function StoryPanel({ chapters, index, onIndex, error, onClose }: Props) {
  const c = chapters?.[index];
  return (
    <div className="pointer-events-auto flex max-h-full w-96 max-w-[calc(100vw-1.5rem)] flex-col rounded-md bg-white shadow-lg">
      <div className="flex items-start justify-between border-b border-stone-200 px-4 py-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-stone-500">
            Story {c ? `· ${c.number} of ${chapters!.length}` : ""}
          </p>
          <p className="text-sm font-semibold text-stone-900">{c?.title ?? "Loading…"}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close story" className="ml-2 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700">
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {error && <p className="text-sm text-red-700">{error}</p>}
        {c && (
          <>
            <div className="mb-3 grid grid-cols-2 gap-2">
              {c.facts.slice(0, 4).map((f) => (
                <div key={f.label} className="rounded-md bg-stone-50 px-2.5 py-2">
                  <p className="text-lg font-semibold tabular-nums leading-tight text-stone-900">
                    {fmt(f.value)} <span className="text-xs font-normal text-stone-500">{f.unit}</span>
                  </p>
                  <p className="mt-0.5 text-[11px] leading-snug text-stone-600">{f.label}</p>
                </div>
              ))}
            </div>
            <Markdown text={c.body} />
            <p className="mt-3 text-[11px] text-stone-500">
              Sources:{" "}
              {c.sources.map((s, i) => (
                <span key={s.dataset_id}>
                  {i > 0 && " · "}
                  <a className="underline decoration-stone-300 underline-offset-2 hover:text-stone-800" href={s.url} target="_blank" rel="noreferrer">
                    {s.dataset_id} ({s.publish_date})
                  </a>
                </span>
              ))}
            </p>
          </>
        )}
      </div>

      {chapters && (
        <div className="flex items-center justify-between border-t border-stone-200 px-4 py-2">
          <button
            type="button"
            disabled={index === 0}
            onClick={() => onIndex(index - 1)}
            className="rounded border border-stone-300 px-3 py-1 text-xs font-medium text-stone-700 disabled:opacity-40"
          >
            ← Back
          </button>
          <div className="flex gap-1" aria-hidden>
            {chapters.map((ch, i) => (
              <button
                key={ch.id}
                type="button"
                onClick={() => onIndex(i)}
                title={ch.title}
                className={`h-2 w-2 rounded-full ${i === index ? "bg-stone-900" : "bg-stone-300 hover:bg-stone-500"}`}
              />
            ))}
          </div>
          <button
            type="button"
            disabled={index === chapters.length - 1}
            onClick={() => onIndex(index + 1)}
            className="rounded bg-stone-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-40"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
