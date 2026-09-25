import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Download, FileDown, Send } from 'lucide-react';
import { useExecutiveSummary, useRuns } from '@/api/forecast/hooks';
import { Markdown } from '@/components/block/markdown';
import {
  EmptyNote,
  LoadingBlock,
  PageHeader,
  Panel,
  RunDot,
  SOURCE_NOTE,
} from '@/components/forecast/common';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { dateTime, RUN_KIND_JA } from '@/lib/forecast/format';
import { useAskAgent } from '@/lib/forecast/store';

function downloadMarkdown(markdown: string, name: string) {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function SummaryPage() {
  const [params] = useSearchParams();
  const id = params.get('id');
  const { data: summary, isLoading } = useExecutiveSummary(id);
  const { data: runs } = useRuns();
  const { ask, ready, running } = useAskAgent();
  const [selected, setSelected] = useState<string[]>(['base-S1_BASE']);
  const [audience, setAudience] = useState('社長報告');

  const toggle = (rid: string, on: boolean) =>
    setSelected(s => (on ? [...s, rid] : s.filter(x => x !== rid)));

  const request = () => {
    const chosen = (runs ?? []).filter(r => selected.includes(r.run_id));
    if (!chosen.length) return;
    void ask(
      `次の予測と補正の履歴をもとに、${audience}向けの1枚サマリーを作成してください：` +
        chosen.map(r => `「${r.label}」(run_id: ${r.run_id})`).join('、')
    );
  };

  return (
    <div>
      <div className="print-hidden">
        <PageHeader
          title="経営会議サマリー"
          description="選んだシナリオと補正を反映した1枚サマリーをエージェントが作成します。PDF はブラウザの印刷機能で保存します。"
          actions={
            summary && (
              <>
                <Button
                  variant="secondary"
                  onClick={() =>
                    downloadMarkdown(summary.markdown, `executive_summary_${summary.summary_id}.md`)
                  }
                >
                  <Download className="size-4" />
                  Markdown
                </Button>
                <Button onClick={() => window.print()}>
                  <FileDown className="size-4" />
                  PDF でダウンロード
                </Button>
              </>
            )
          }
        />
      </div>
      <div className="grid gap-4">
        <div className="print-hidden">
          <Panel title="サマリーの対象">
            <div className="flex flex-wrap gap-x-6 gap-y-1.5">
              {(runs ?? []).map(r => (
                <label key={r.run_id} className="flex cursor-pointer items-center gap-2 text-sm">
                  <Checkbox
                    checked={selected.includes(r.run_id)}
                    onCheckedChange={v => toggle(r.run_id, v === true)}
                  />
                  <RunDot run={r} />
                  <span className="truncate">{r.label}</span>
                  {r.kind !== 'base' && (
                    <span className="text-xs text-muted-foreground">{RUN_KIND_JA[r.kind]}</span>
                  )}
                </label>
              ))}
            </div>
            <div className="mt-3 space-y-1">
              <Label className="text-xs" htmlFor="audience">
                読み手
              </Label>
              <Input id="audience" value={audience} onChange={e => setAudience(e.target.value)} />
            </div>
            <Button className="mt-3" onClick={request} disabled={!ready || !selected.length}>
              <Send className="size-4" />
              {running ? 'エージェントが処理中です…' : 'サマリーを作成'}
            </Button>
          </Panel>
        </div>
        <Panel
          title={summary ? `プレビュー（${dateTime(summary.created_at)} 作成）` : 'プレビュー'}
          className="summary-print"
        >
          {isLoading ? (
            <LoadingBlock />
          ) : !summary ? (
            <EmptyNote>
              まだサマリーはありません。左で対象を選んで「サマリーを作成」を押すか、チャットで「今日の議論を社長報告用に1枚にまとめて」と依頼してください。
            </EmptyNote>
          ) : (
            <article className="prose-sm max-w-none text-sm">
              <Markdown>{summary.markdown}</Markdown>
              <p className="mt-6 border-t border-border pt-2 text-xs text-muted-foreground">
                出典・注記：{SOURCE_NOTE}
              </p>
            </article>
          )}
        </Panel>
      </div>
    </div>
  );
}
