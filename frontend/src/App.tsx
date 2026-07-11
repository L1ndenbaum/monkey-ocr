import { Activity, KeyRound, LogOut, ScanText, ServerCog } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useJobs, useJobSubscription, useSessionApiKey } from "./application/useWorkspace";
import { ApiKeyGate } from "./components/ApiKeyGate";
import { JobDetail } from "./components/JobDetail";
import { JobList } from "./components/JobList";
import { UploadPanel } from "./components/UploadPanel";
import { isActiveJob } from "./domain/ocr";
import { toUserError } from "./domain/api";
import { clearApiKey, maskApiKey } from "./infrastructure/auth/apiKeyStore";

export default function App() {
  const apiKey = useSessionApiKey();
  const workspace = useJobs(Boolean(apiKey));
  const [selectedId, setSelectedId] = useState<string>();

  useEffect(() => {
    if (!apiKey) setSelectedId(undefined);
  }, [apiKey]);

  useEffect(() => {
    if (!selectedId && workspace.jobs.length) setSelectedId(workspace.jobs[0].job_id);
    if (selectedId && workspace.jobs.length && !workspace.jobs.some((job) => job.job_id === selectedId)) {
      setSelectedId(workspace.jobs[0].job_id);
    }
  }, [selectedId, workspace.jobs]);

  const selectedJob = workspace.jobs.find((job) => job.job_id === selectedId);
  const connection = useJobSubscription(selectedJob, workspace.updateFromEvent, workspace.refreshJob);
  const activeCount = useMemo(
    () => workspace.jobs.filter((job) => isActiveJob(job.status)).length,
    [workspace.jobs],
  );

  if (!apiKey) return <ApiKeyGate />;

  return (
    <main className="relative min-h-screen overflow-hidden bg-paper text-ink">
      <div className="grain" aria-hidden="true" />
      <div className="pointer-events-none absolute -left-24 top-1/3 h-80 w-80 rounded-full bg-[#d8e4d7] opacity-60 blur-3xl" />
      <div className="pointer-events-none absolute right-0 top-0 h-96 w-96 rounded-full bg-[#ead9c6] opacity-55 blur-3xl" />

      <div className="relative mx-auto max-w-[1600px] px-4 py-5 sm:px-6 lg:px-8">
        <header className="mb-5 flex flex-wrap items-center justify-between gap-4 px-1">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-2xl bg-ink text-paper shadow-lg">
              <ScanText size={23} strokeWidth={1.8} />
            </span>
            <div>
              <p className="font-display text-xl font-semibold tracking-tight">MonkeyOCR</p>
              <p className="text-[10px] font-medium uppercase tracking-[0.2em] text-black/40">Async workspace</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="hidden items-center gap-2 rounded-full border border-black/8 bg-white/55 px-3 py-2 text-xs text-black/55 backdrop-blur sm:flex">
              <Activity size={14} className={activeCount ? "text-emerald-600" : "text-black/30"} />
              {activeCount ? `${activeCount} 个任务运行中` : "队列空闲"}
            </div>
            <div className="flex items-center gap-2 rounded-full border border-black/8 bg-white/55 py-1.5 pl-3 pr-1.5 backdrop-blur">
              <KeyRound size={13} className="text-black/40" />
              <span className="hidden font-mono text-[11px] text-black/50 sm:block">{maskApiKey(apiKey)}</span>
              <button
                type="button"
                aria-label="退出当前 API Key"
                title="清除当前会话中的 API Key"
                onClick={clearApiKey}
                className="rounded-full p-1.5 text-black/40 transition hover:bg-black/5 hover:text-red-600"
              >
                <LogOut size={15} />
              </button>
            </div>
          </div>
        </header>

        {workspace.error !== null && (
          <div className="mb-4 flex items-start justify-between gap-3 rounded-2xl border border-red-100 bg-red-50/90 px-4 py-3 text-sm text-red-800">
            <span>{toUserError(workspace.error)}</span>
            <button type="button" onClick={() => workspace.setError(null)} className="shrink-0 text-xs font-semibold">关闭</button>
          </div>
        )}

        <div className="grid gap-5 lg:grid-cols-[22rem_minmax(0,1fr)] xl:grid-cols-[24rem_minmax(0,1fr)]">
          <aside className="space-y-5">
            <UploadPanel
              onCreated={(job) => {
                workspace.upsertJob(job);
                setSelectedId(job.job_id);
              }}
            />
            <JobList
              jobs={workspace.jobs}
              selectedId={selectedId}
              loading={workspace.loading}
              onSelect={setSelectedId}
              onRefresh={() => void workspace.refresh()}
            />
          </aside>
          <JobDetail job={selectedJob} connection={connection} onChanged={workspace.upsertJob} />
        </div>

        <footer className="mt-5 flex items-center justify-center gap-2 text-[11px] text-black/35 lg:hidden">
          <ServerCog size={13} />
          结果与任务状态以服务端记录为准
        </footer>
      </div>
    </main>
  );
}
