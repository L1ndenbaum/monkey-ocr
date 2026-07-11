import * as Progress from "@radix-ui/react-progress";
import { ChangeEvent, DragEvent, useRef, useState } from "react";
import { FileImage, FileText, UploadCloud, X } from "lucide-react";
import type { OcrJob } from "../domain/ocr";
import { toUserError } from "../domain/api";
import { createJob } from "../infrastructure/api/jobs";
import {
  uploadDocument,
  type UploadProgress,
  type UploadStage,
} from "../infrastructure/api/uploads";
import { formatBytes } from "../lib/format";

interface Props {
  onCreated: (job: OcrJob) => void;
}

const STAGE_LABELS: Record<UploadStage, string> = {
  hashing: "计算文件指纹",
  creating: "创建安全上传",
  uploading: "上传到对象存储",
  verifying: "校验文件真实性",
};

const ACCEPTED_TYPES = new Set(["application/pdf", "image/png", "image/jpeg", "image/webp", "image/bmp", "image/tiff"]);

export function UploadPanel({ onCreated }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const select = (next: File | undefined) => {
    setError(null);
    setProgress(null);
    if (!next) return;
    if (!ACCEPTED_TYPES.has(next.type)) {
      setError("仅支持 PDF、PNG、JPEG、WebP 与 TIFF 文件");
      return;
    }
    setFile(next);
  };

  const onInput = (event: ChangeEvent<HTMLInputElement>) => select(event.target.files?.[0]);
  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    select(event.dataTransfer.files?.[0]);
  };

  const submit = async () => {
    if (!file || working) return;
    setWorking(true);
    setError(null);
    try {
      const upload = await uploadDocument(file, setProgress);
      const job = await createJob(upload.completed.upload_id);
      onCreated(job);
      setFile(null);
      setProgress(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (nextError) {
      setError(toUserError(nextError));
    } finally {
      setWorking(false);
    }
  };

  return (
    <section className="rounded-[1.75rem] border border-black/10 bg-white/75 p-5 shadow-soft backdrop-blur sm:p-6">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <p className="eyebrow">New document</p>
          <h2 className="font-display text-2xl font-semibold tracking-tight">创建识别任务</h2>
        </div>
        <span className="hidden rounded-full bg-moss/10 px-3 py-1 text-xs font-medium text-moss sm:block">
          PDF · IMAGE
        </span>
      </div>

      {!file ? (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragEnter={() => setDragging(true)}
          onDragLeave={() => setDragging(false)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
          className={`group flex w-full flex-col items-center rounded-2xl border border-dashed px-6 py-9 text-center transition ${
            dragging ? "border-moss bg-moss/10" : "border-black/20 bg-paper/55 hover:border-moss/60 hover:bg-moss/5"
          }`}
        >
          <span className="mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-white text-moss shadow-sm transition group-hover:-translate-y-0.5">
            <UploadCloud size={23} />
          </span>
          <strong className="text-sm">拖入文件，或点击选择</strong>
          <span className="mt-1 text-xs text-black/45">上传前会在本地计算 SHA-256</span>
        </button>
      ) : (
        <div className="rounded-2xl border border-black/10 bg-paper/60 p-4">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-white text-clay shadow-sm">
              {file.type === "application/pdf" ? <FileText size={21} /> : <FileImage size={21} />}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">{file.name}</p>
              <p className="mt-0.5 text-xs text-black/45">{formatBytes(file.size)}</p>
            </div>
            {!working && (
              <button
                type="button"
                aria-label="移除文件"
                onClick={() => setFile(null)}
                className="rounded-lg p-2 text-black/35 transition hover:bg-black/5 hover:text-black"
              >
                <X size={17} />
              </button>
            )}
          </div>

          {progress && (
            <div className="mt-5">
              <div className="mb-2 flex justify-between text-xs">
                <span className="font-medium text-moss">{STAGE_LABELS[progress.stage]}</span>
                <span className="tabular-nums text-black/45">{Math.round(progress.percent)}%</span>
              </div>
              <Progress.Root
                className="relative h-1.5 overflow-hidden rounded-full bg-black/10"
                value={progress.percent}
              >
                <Progress.Indicator
                  className="h-full rounded-full bg-moss transition-transform duration-300"
                  style={{ transform: `translateX(-${100 - progress.percent}%)` }}
                />
              </Progress.Root>
            </div>
          )}

          <button
            type="button"
            disabled={working}
            onClick={() => void submit()}
            className="mt-5 w-full rounded-xl bg-ink px-4 py-3 text-sm font-semibold text-white transition hover:bg-moss disabled:cursor-wait disabled:opacity-60"
          >
            {working ? "正在安全上传…" : "上传并开始识别"}
          </button>
        </div>
      )}

      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept="application/pdf,image/png,image/jpeg,image/webp,image/bmp,image/tiff"
        onChange={onInput}
      />
      {error && <p className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">{error}</p>}
    </section>
  );
}
