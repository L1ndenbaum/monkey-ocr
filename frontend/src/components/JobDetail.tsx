import * as Dialog from "@radix-ui/react-dialog";
import * as Progress from "@radix-ui/react-progress";
import * as Tabs from "@radix-ui/react-tabs";
import {
  Ban,
  CheckCircle2,
  Clock3,
  Download,
  ExternalLink,
  FileJson,
  FileText,
  ImageIcon,
  LoaderCircle,
  RefreshCcw,
  ScanLine,
  X,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { JobArtifact, OcrJob } from "../domain/ocr";
import { isActiveJob } from "../domain/ocr";
import { toUserError } from "../domain/api";
import {
  cancelJob,
  listArtifacts,
  loadTextArtifact,
  retryJob,
} from "../infrastructure/api/jobs";
import { formatBytes, formatDate, shortenId, statusLabel } from "../lib/format";
import type { LiveConnection } from "../application/useWorkspace";

interface Props {
  job?: OcrJob;
  connection: LiveConnection;
  onChanged: (job: OcrJob) => void;
}

function statusIcon(job: OcrJob) {
  if (job.status === "succeeded") return <CheckCircle2 className="text-emerald-600" size={22} />;
  if (job.status === "failed") return <XCircle className="text-red-600" size={22} />;
  if (job.status === "cancelled") return <Ban className="text-stone-500" size={22} />;
  return <LoaderCircle className="animate-spin text-moss" size={22} />;
}

function artifactIcon(artifact: JobArtifact) {
  if (artifact.kind === "markdown") return <FileText size={18} />;
  if (artifact.kind === "json" || artifact.kind === "manifest") return <FileJson size={18} />;
  return <ImageIcon size={18} />;
}

export function JobDetail({ job, connection, onChanged }: Props) {
  const [artifacts, setArtifacts] = useState<JobArtifact[]>([]);
  const [markdown, setMarkdown] = useState<string>("");
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [action, setAction] = useState<"cancel" | "retry" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewImage, setPreviewImage] = useState<JobArtifact | null>(null);

  useEffect(() => {
    setArtifacts([]);
    setMarkdown("");
    setError(null);
    if (!job || job.status !== "succeeded") return;

    let disposed = false;
    const load = async () => {
      try {
        const items = await listArtifacts(job.job_id);
        if (disposed) return;
        setArtifacts(items);
        const markdownArtifact = items.find((item) => item.kind === "markdown");
        if (markdownArtifact) {
          const content = await loadTextArtifact(markdownArtifact);
          if (!disposed) setMarkdown(content);
        }
      } catch (nextError) {
        if (!disposed) setError(toUserError(nextError));
      } finally {
        if (!disposed) setArtifactsLoading(false);
      }
    };
    setArtifactsLoading(true);
    void load();
    const configuredRefresh = Number(import.meta.env.VITE_ARTIFACT_REFRESH_MS || 600_000);
    const refreshMs = Number.isFinite(configuredRefresh)
      ? Math.max(60_000, configuredRefresh)
      : 600_000;
    const timer = window.setInterval(() => void load(), refreshMs);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [job?.job_id, job?.status]);

  const images = useMemo(
    () => artifacts.filter((item) => item.kind === "page_image" || item.kind === "visualization"),
    [artifacts],
  );

  const perform = async (kind: "cancel" | "retry") => {
    if (!job) return;
    setAction(kind);
    setError(null);
    try {
      onChanged(kind === "cancel" ? await cancelJob(job.job_id) : await retryJob(job.job_id));
    } catch (nextError) {
      setError(toUserError(nextError));
    } finally {
      setAction(null);
    }
  };

  if (!job) {
    return (
      <section className="grid min-h-[34rem] place-items-center rounded-[1.75rem] border border-black/10 bg-white/55 p-8 shadow-soft backdrop-blur lg:h-[calc(100vh-8.5rem)]">
        <div className="max-w-xs text-center text-black/40">
          <span className="mx-auto grid h-16 w-16 place-items-center rounded-3xl bg-moss/10 text-moss">
            <ScanLine size={29} strokeWidth={1.5} />
          </span>
          <p className="mt-5 font-display text-xl font-semibold text-black/60">选择一个任务</p>
          <p className="mt-2 text-sm leading-6">这里会显示实时页级进度、识别结果和可下载的产物。</p>
        </div>
      </section>
    );
  }

  return (
    <section className="flex min-h-[40rem] flex-col overflow-hidden rounded-[1.75rem] border border-black/10 bg-white/80 shadow-soft backdrop-blur lg:h-[calc(100vh-8.5rem)]">
      <header className="border-b border-black/8 px-5 py-5 sm:px-7 sm:py-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="eyebrow">Job · {shortenId(job.job_id)}</p>
            <h2 className="mt-1 truncate font-display text-2xl font-semibold tracking-tight sm:text-3xl">
              {job.filename}
            </h2>
          </div>
          <div className="flex items-center gap-2 rounded-full border border-black/8 bg-paper/70 py-1.5 pl-2 pr-3 text-xs font-semibold">
            {statusIcon(job)}
            {statusLabel(job.status)}
          </div>
        </div>

        <div className="mt-6">
          <div className="mb-2 flex items-end justify-between">
            <span className="text-xs font-medium text-black/50">
              {job.progress.total_pages
                ? `${job.progress.completed_pages} / ${job.progress.total_pages} 页`
                : "正在准备页面"}
            </span>
            <span className="font-display text-2xl font-semibold tabular-nums">
              {Math.round(job.progress.percent)}%
            </span>
          </div>
          <Progress.Root className="relative h-2 overflow-hidden rounded-full bg-black/8" value={job.progress.percent}>
            <Progress.Indicator
              className={`h-full rounded-full transition-transform duration-500 ${job.status === "failed" ? "bg-red-500" : "bg-moss"}`}
              style={{ transform: `translateX(-${100 - job.progress.percent}%)` }}
            />
          </Progress.Root>
          {isActiveJob(job.status) && (
            <p className="mt-2 flex items-center gap-1.5 text-[11px] text-black/40">
              <span className={`h-1.5 w-1.5 rounded-full ${connection === "open" ? "bg-emerald-500" : "animate-pulse bg-amber-500"}`} />
              {connection === "open" ? "实时进度已连接" : "实时流重连中，正在轮询兜底"}
            </p>
          )}
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {isActiveJob(job.status) && job.status !== "cancel_requested" && (
            <button
              type="button"
              disabled={action !== null}
              onClick={() => void perform("cancel")}
              className="inline-flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-2 text-xs font-semibold text-red-700 transition hover:bg-red-100 disabled:opacity-50"
            >
              {action === "cancel" ? <LoaderCircle size={14} className="animate-spin" /> : <Ban size={14} />}
              取消任务
            </button>
          )}
          {(job.status === "failed" || job.status === "cancelled") && (
            <button
              type="button"
              disabled={action !== null}
              onClick={() => void perform("retry")}
              className="inline-flex items-center gap-2 rounded-xl bg-ink px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-moss disabled:opacity-50"
            >
              {action === "retry" ? <LoaderCircle size={14} className="animate-spin" /> : <RefreshCcw size={14} />}
              断点续跑
            </button>
          )}
        </div>
        {error && <p className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">{error}</p>}
      </header>

      <Tabs.Root defaultValue="overview" className="flex min-h-0 flex-1 flex-col">
        <Tabs.List className="flex gap-1 overflow-x-auto border-b border-black/8 px-4 pt-3 sm:px-6">
          {[
            ["overview", "概览"],
            ["markdown", "Markdown"],
            ["images", `图片${images.length ? ` ${images.length}` : ""}`],
            ["artifacts", `产物${artifacts.length ? ` ${artifacts.length}` : ""}`],
          ].map(([value, label]) => (
            <Tabs.Trigger key={value} value={value} className="tab-trigger">
              {label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <Tabs.Content value="overview" className="p-5 sm:p-7">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <Info label="创建时间" value={formatDate(job.created_at)} icon={<Clock3 size={16} />} />
              <Info label="执行次数" value={`第 ${job.attempt} 次`} icon={<RefreshCcw size={16} />} />
              <Info label="识别引擎" value={job.engine_name || "PaddleOCR-VL"} icon={<ScanLine size={16} />} />
              <Info label="总页数" value={job.progress.total_pages ? `${job.progress.total_pages} 页` : "分析中"} />
              <Info label="当前页面" value={job.progress.current_page ? `第 ${job.progress.current_page} 页` : "—"} />
              <Info label="引擎版本" value={job.engine_version || "由服务端记录"} />
              <Info label="模型" value={job.model_name || "由服务端记录"} />
            </div>
            {(job.error_message || job.error_reason) && (
              <div className="mt-5 rounded-2xl border border-red-100 bg-red-50 p-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-red-500">Failure</p>
                <p className="mt-2 text-sm leading-6 text-red-800">{job.error_message || job.error_reason}</p>
                {job.internal_code !== undefined && job.internal_code !== 0 && (
                  <p className="mt-2 font-mono text-xs text-red-600">internal_code={job.internal_code}</p>
                )}
              </div>
            )}
          </Tabs.Content>

          <Tabs.Content value="markdown" className="p-5 sm:p-7">
            {artifactsLoading ? (
              <LoadingResult />
            ) : markdown ? (
              <article className="markdown-preview">
                <ReactMarkdown>{markdown}</ReactMarkdown>
              </article>
            ) : (
              <EmptyResult text={job.status === "succeeded" ? "任务没有生成 Markdown 产物" : "识别完成后可在这里预览 Markdown"} />
            )}
          </Tabs.Content>

          <Tabs.Content value="images" className="p-5 sm:p-7">
            {artifactsLoading ? (
              <LoadingResult />
            ) : images.length ? (
              <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
                {images.map((image) => (
                  <button
                    type="button"
                    key={image.artifact_id}
                    onClick={() => setPreviewImage(image)}
                    className="group overflow-hidden rounded-2xl border border-black/10 bg-paper text-left"
                  >
                    <img src={image.download_url} alt={image.name} loading="lazy" className="aspect-[4/3] w-full object-cover transition group-hover:scale-[1.02]" />
                    <span className="block truncate px-3 py-2 text-xs font-medium">{image.name}</span>
                  </button>
                ))}
              </div>
            ) : (
              <EmptyResult text="识别完成后可查看规范化页图与可视化结果" />
            )}
          </Tabs.Content>

          <Tabs.Content value="artifacts" className="p-5 sm:p-7">
            {artifactsLoading ? (
              <LoadingResult />
            ) : artifacts.length ? (
              <div className="space-y-2">
                {artifacts.map((artifact) => (
                  <a
                    key={artifact.artifact_id}
                    href={artifact.download_url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-3 rounded-2xl border border-black/8 p-3 transition hover:border-moss/30 hover:bg-moss/5"
                  >
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-paper text-moss">
                      {artifactIcon(artifact)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold">{artifact.name}</span>
                      <span className="mt-0.5 block text-[11px] text-black/40">
                        {artifact.mime_type} · {formatBytes(artifact.size_bytes)}
                      </span>
                    </span>
                    <Download size={17} className="text-black/35" />
                  </a>
                ))}
              </div>
            ) : (
              <EmptyResult text="任务完成后会生成 Markdown、JSON、图片和 manifest" />
            )}
          </Tabs.Content>
        </div>
      </Tabs.Root>

      <Dialog.Root open={previewImage !== null} onOpenChange={(open) => !open && setPreviewImage(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/65 backdrop-blur-sm" />
          <Dialog.Content className="fixed inset-4 z-50 flex flex-col overflow-hidden rounded-2xl bg-white shadow-2xl sm:inset-10">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <Dialog.Title className="truncate text-sm font-semibold">{previewImage?.name}</Dialog.Title>
              <div className="flex gap-1">
                {previewImage && (
                  <a href={previewImage.download_url} target="_blank" rel="noreferrer" className="rounded-lg p-2 hover:bg-black/5" aria-label="在新窗口打开">
                    <ExternalLink size={17} />
                  </a>
                )}
                <Dialog.Close className="rounded-lg p-2 hover:bg-black/5" aria-label="关闭预览"><X size={18} /></Dialog.Close>
              </div>
            </div>
            <div className="grid min-h-0 flex-1 place-items-center overflow-auto bg-black/5 p-4">
              {previewImage && <img src={previewImage.download_url} alt={previewImage.name} className="max-h-full max-w-full object-contain" />}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}

function Info({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-black/8 bg-paper/55 p-4">
      <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-black/40">{icon}{label}</p>
      <p className="mt-2 truncate text-sm font-semibold">{value}</p>
    </div>
  );
}

function LoadingResult() {
  return <div className="grid min-h-48 place-items-center text-black/35"><LoaderCircle className="animate-spin" /></div>;
}

function EmptyResult({ text }: { text: string }) {
  return <div className="grid min-h-48 place-items-center rounded-2xl border border-dashed border-black/15 bg-paper/40 px-6 text-center text-sm text-black/40">{text}</div>;
}
