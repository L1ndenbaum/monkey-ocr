import * as ScrollArea from "@radix-ui/react-scroll-area";
import { FileSearch, LoaderCircle, RefreshCw } from "lucide-react";
import type { OcrJob } from "../domain/ocr";
import { formatDate, statusLabel } from "../lib/format";

interface Props {
  jobs: OcrJob[];
  selectedId?: string;
  loading: boolean;
  onSelect: (jobId: string) => void;
  onRefresh: () => void;
}

const statusTone: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-stone-200 text-stone-600",
  running: "bg-blue-100 text-blue-700",
  preprocessing: "bg-blue-100 text-blue-700",
  assembling: "bg-violet-100 text-violet-700",
};

export function JobList({ jobs, selectedId, loading, onSelect, onRefresh }: Props) {
  return (
    <section className="flex min-h-[24rem] flex-col rounded-[1.75rem] border border-black/10 bg-white/75 shadow-soft backdrop-blur lg:h-[calc(100vh-8.5rem)] lg:min-h-[38rem]">
      <div className="flex items-center justify-between border-b border-black/8 px-5 py-5">
        <div>
          <p className="eyebrow">Recent jobs</p>
          <h2 className="font-display text-2xl font-semibold tracking-tight">识别队列</h2>
        </div>
        <button
          type="button"
          aria-label="刷新任务"
          onClick={onRefresh}
          disabled={loading}
          className="rounded-xl border border-black/10 bg-white p-2.5 text-black/55 transition hover:text-moss disabled:opacity-40"
        >
          <RefreshCw size={17} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <ScrollArea.Root className="min-h-0 flex-1 overflow-hidden">
        <ScrollArea.Viewport className="h-full w-full p-3">
          {loading && jobs.length === 0 ? (
            <div className="grid min-h-64 place-items-center text-black/35">
              <LoaderCircle className="animate-spin" />
            </div>
          ) : jobs.length === 0 ? (
            <div className="flex min-h-64 flex-col items-center justify-center px-8 text-center text-black/40">
              <FileSearch size={30} strokeWidth={1.5} />
              <p className="mt-3 text-sm font-medium text-black/55">还没有识别任务</p>
              <p className="mt-1 text-xs">上传第一份文档后，进度会显示在这里。</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {jobs.map((job) => (
                <button
                  key={job.job_id}
                  type="button"
                  onClick={() => onSelect(job.job_id)}
                  className={`w-full rounded-2xl border p-3.5 text-left transition ${
                    selectedId === job.job_id
                      ? "border-moss/30 bg-moss/10"
                      : "border-transparent hover:border-black/8 hover:bg-black/[0.025]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 truncate text-sm font-semibold text-ink">{job.filename}</p>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${statusTone[job.status] || "bg-amber-100 text-amber-800"}`}>
                      {statusLabel(job.status)}
                    </span>
                  </div>
                  <div className="mt-2.5 flex items-center justify-between text-[11px] text-black/40">
                    <span>{formatDate(job.created_at)}</span>
                    <span className="tabular-nums">
                      {job.progress.total_pages > 0
                        ? `${job.progress.completed_pages}/${job.progress.total_pages} 页`
                        : `第 ${job.attempt} 次尝试`}
                    </span>
                  </div>
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-black/8">
                    <div
                      className={`h-full rounded-full transition-all ${job.status === "failed" ? "bg-red-400" : "bg-moss"}`}
                      style={{ width: `${job.progress.percent}%` }}
                    />
                  </div>
                </button>
              ))}
            </div>
          )}
        </ScrollArea.Viewport>
        <ScrollArea.Scrollbar orientation="vertical" className="flex w-2.5 touch-none p-0.5">
          <ScrollArea.Thumb className="relative flex-1 rounded-full bg-black/15" />
        </ScrollArea.Scrollbar>
      </ScrollArea.Root>
    </section>
  );
}
