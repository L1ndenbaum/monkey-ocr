import { FormEvent, useState } from "react";
import { KeyRound, ScanText } from "lucide-react";
import { setApiKey } from "../infrastructure/auth/apiKeyStore";

export function ApiKeyGate() {
  const [value, setValue] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (value.trim()) setApiKey(value);
  };

  return (
    <main className="relative grid min-h-screen place-items-center overflow-hidden bg-paper px-5 py-12 text-ink">
      <div className="grain" aria-hidden="true" />
      <div className="absolute -left-32 top-8 h-96 w-96 rounded-full bg-[#d6e2d5] blur-3xl" />
      <div className="absolute -right-32 bottom-0 h-96 w-96 rounded-full bg-[#ead4c2] blur-3xl" />
      <section className="relative w-full max-w-lg overflow-hidden rounded-[2rem] border border-black/10 bg-white/70 p-8 shadow-soft backdrop-blur-xl sm:p-12">
        <div className="mb-10 flex items-center gap-3">
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-ink text-paper">
            <ScanText size={25} strokeWidth={1.8} />
          </span>
          <div>
            <p className="font-display text-2xl font-semibold tracking-tight">MonkeyOCR</p>
            <p className="text-xs uppercase tracking-[0.22em] text-black/45">Document workspace</p>
          </div>
        </div>

        <p className="mb-2 font-display text-4xl leading-tight tracking-tight sm:text-5xl">
          让文档变成
          <br />
          可用的数据。
        </p>
        <p className="mb-9 mt-5 max-w-sm text-sm leading-6 text-black/55">
          输入管理员签发的 API Key，开始上传 PDF 或图片。Key 只保存在当前浏览器会话中。
        </p>

        <form onSubmit={submit} className="space-y-3">
          <label className="block text-xs font-semibold uppercase tracking-[0.16em] text-black/55" htmlFor="api-key">
            API Key
          </label>
          <div className="flex rounded-2xl border border-black/15 bg-white p-1.5 shadow-sm transition focus-within:border-moss/60 focus-within:ring-4 focus-within:ring-moss/10">
            <span className="grid w-11 place-items-center text-black/40">
              <KeyRound size={18} />
            </span>
            <input
              id="api-key"
              autoFocus
              type="password"
              autoComplete="off"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder="mocr_••••••••••••"
              className="min-w-0 flex-1 bg-transparent px-1 py-3 font-mono text-sm outline-none placeholder:text-black/25"
            />
            <button
              type="submit"
              disabled={!value.trim()}
              className="rounded-xl bg-ink px-5 text-sm font-medium text-white transition hover:bg-moss disabled:cursor-not-allowed disabled:opacity-35"
            >
              进入
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
