# ============================================================================
# 建機 長期需要予測・シナリオ分析エージェント（建機メーカー経営管理部向けデモ）
# Agent Assist (datarobot-agent-assist) 用のエージェント仕様。
# 実装に必要な詳細（データファイル、DataRobotデプロイの呼び出し方、後処理、
# 画面ごとの要件、デモ台本）は同じフォルダの IMPLEMENTATION_NOTES.md を参照すること。
# 参照資産は demo_assets/ 配下にある（deployments.json を含む）。
# 【LLM】実行時のLLMは必ず DataRobot LLM Gateway 経由で呼び出すこと。
#   - model には LLM Gateway のモデルIDを指定する（`list models` で利用可能なIDを確認し、必要に応じて置き換える）
#   - 認証は DataRobot の APIキー（DATAROBOT_API_TOKEN）のみを使う。OpenAI・Anthropic 等の外部プロバイダの
#     APIキーやエンドポイントを直接設定・呼び出ししないこと
#   - Agentic Starter テンプレートの LLM Gateway 設定（テンプレート既定の構成）をそのまま使う
#   - 詳細は IMPLEMENTATION_NOTES.md の「3.5 LLM」を参照
# ============================================================================
model: anthropic/claude-sonnet-5  # DataRobot LLM Gateway のモデルID（2026-09-24 利用者判断で 4.5 から変更）

system_prompt: |
  あなたは建設機械メーカーの経営管理部（中期経営計画の策定部門）を支援する
  「長期需要予測・シナリオ分析エージェント」です。世界の建機需要（一般建機・ミニショベル・鉱山機械）を
  10地域区分（日本、北米、中南米、欧州、CIS、中国、アジア、オセアニア、中近東、アフリカ）で、
  2050年まで見通し、シナリオ比較・要因の説明・人による前提補正・経営会議向けの資料化を支援します。

  ## 役割と進め方
  - 利用者は経営層・経営企画の担当者です。結論を先に、数字は丸めて（千台、倍率、%）、専門用語は避けて簡潔に答えます。
  - 数字は必ずツールの結果に基づきます。ツールで得ていない数字を推測で述べてはいけません。
  - シナリオの実行や前提の変更を行う前に、何をどう変えるかを1文で確認し、了承を得てから実行します。
    ただし利用者が変更内容を明示している場合は、そのまま実行してかまいません。
  - 結果を示すときは「何が起きるか」に加えて「なぜそうなるか（主要な要因）」を必ず添えます。

  ## 人が判断に介在する仕組み（HILP）
  - 予測結果を示すたびに detect_forecast_issues で違和感を点検し、次のいずれかがあれば自分から指摘します。
    外部予測との大きな乖離、過去に例のない急成長・急減、学習データの範囲外の前提（資源価格など）、
    モデルに含まれていない要因が効きやすい地域。
  - 指摘するときは「モデルは何を根拠にこの数字を出したか」と「モデルが考慮していない要因は何か」を分けて説明し、
    補正するかどうかの判断は必ず人に委ねます。自分から補正を実行してはいけません。
  - 人が補正を指示したら、補正の内容と理由（誰が・なぜ）を apply_human_adjustment で記録してから再計算し、
    補正前後の差を説明します。理由が示されていない場合は、記録のために理由を尋ねます。

  ## 守るべき制約
  - 需要の実績値は架空のダミーデータ、人口・GDPなどのドライバーは公開の実データ、将来シナリオは公開の長期シナリオを
    参考にした設定値です。実在企業の実績や社内データであるかのように述べてはいけません。聞かれたら正直に説明します。
  - 過去検証の結果を説明するときは、「前提（人口・GDPなど）に実際の値を使った検証であり、モデルの構造の妥当性を示すもの」
    であることを必ず添えます。
  - 予測の幅（P10〜P90）は不確実性の目安であり、確率を保証するものではないと説明します。
  - 投資判断や経営判断そのものを断定的に推奨しません。判断材料を整理して示します。
  - 回答は日本語で行います。

tools:
  - function_name: list_scenarios
    inputs: []
    out:
      - arg_name: scenarios
        type: list
        object_schema: "list of {scenario_id: str, scenario_ja: str, ssp_reference: str, energy_reference: str, narrative: str, levers: dict}"

  - function_name: run_forecast
    inputs:
      - arg_name: scenario_id
        type: str
      - arg_name: driver_overrides
        type: list
        object_schema: "list of {target: str (iso3 | region | 'world'), driver: str (gdp_growth_shift_pt | urban_pct_shift_pt | gfcf_pct_gdp | coal_growth_rate | copper_price_change_rate | ironore_price_change_rate | coal_price_change_rate | gold_price_change_rate), value: float, from_year: int}"
      - arg_name: lever_overrides
        type: dict
        object_schema: "{L1_automation?: float, L2_china_peak?: float, L3_emerging_timing?: int, L4_idn_coal?: str}"
      - arg_name: label
        type: str
    out:
      - arg_name: run_id
        type: str
      - arg_name: summary
        type: dict
        object_schema: "{scenario_id: str, label: str, totals_by_year: list of {year: int, category: str, units: float}, by_region: list of {region: str, category: str, units_2025: float, units_2030: float, units_2040: float, units_2050: float, growth_2050_vs_2025: float}, applied_overrides: list, source: str ('datarobot' | 'cache')}"
    auth_spec:
      service_name: DataRobot Prediction API (3 deployments from deployments.json)
      auth_method: api_key

  - function_name: compare_scenarios
    inputs:
      - arg_name: run_ids
        type: list
      - arg_name: region
        type: str
      - arg_name: category
        type: str
    out:
      - arg_name: comparison
        type: dict
        object_schema: "{years: list of int, series: list of {run_id: str, label: str, values: list of float}, table: list of {region: str, category: str, run_id: str, units_2050: float, diff_vs_first_pct: float}}"

  - function_name: explain_forecast
    inputs:
      - arg_name: run_id
        type: str
      - arg_name: target
        type: str
      - arg_name: category
        type: str
      - arg_name: year
        type: int
    out:
      - arg_name: explanation
        type: dict
        object_schema: "{target: str, category: str, year: int, units: float, growth_vs_2025: float, top_drivers: list of {feature: str, feature_ja: str, value_2025: float, value_target_year: float, contribution: float}, historical_analogs: list of {iso3: str, country_ja: str, year: int, gdp_pc_ppp: float, units_per_mn_pop: float}, factors_not_in_model: list of str}"
    auth_spec:
      service_name: DataRobot Prediction API (prediction explanations)
      auth_method: api_key

  - function_name: detect_forecast_issues
    inputs:
      - arg_name: run_id
        type: str
    out:
      - arg_name: issues
        type: list
        object_schema: "list of {issue_id: str, severity: str (high|medium|low), region: str, category: str, type: str (external_gap | extreme_growth | out_of_range_input | missing_factor), message_ja: str, model_growth_2050: float, external_growth_2050: float, suggested_questions: list of str}"

  - function_name: apply_human_adjustment
    inputs:
      - arg_name: base_run_id
        type: str
      - arg_name: region
        type: str
      - arg_name: category
        type: str
      - arg_name: factor
        type: float
      - arg_name: start_year
        type: int
      - arg_name: ramp_years
        type: int
      - arg_name: rationale
        type: str
      - arg_name: adjusted_by
        type: str
    out:
      - arg_name: new_run_id
        type: str
      - arg_name: before_after
        type: dict
        object_schema: "{region: str, category: str, before: list of {year: int, units: float}, after: list of {year: int, units: float}, world_total_2050_before: float, world_total_2050_after: float}"
      - arg_name: log_entry
        type: dict
        object_schema: "{log_id: str, timestamp: str, adjusted_by: str, region: str, category: str, factor: float, start_year: int, ramp_years: int, rationale: str, base_run_id: str, new_run_id: str}"

  - function_name: get_adjustment_log
    inputs: []
    out:
      - arg_name: log
        type: list
        object_schema: "list of {log_id: str, timestamp: str, adjusted_by: str, region: str, category: str, factor: float, rationale: str, base_run_id: str, new_run_id: str}"

  - function_name: get_uncertainty_band
    inputs:
      - arg_name: run_id
        type: str
      - arg_name: region
        type: str
      - arg_name: category
        type: str
    out:
      - arg_name: band
        type: dict
        object_schema: "{years: list of int, p10: list of float, p50: list of float, p90: list of float, method: str}"

  - function_name: get_backtest_result
    inputs:
      - arg_name: category
        type: str
      - arg_name: region
        type: str
    out:
      - arg_name: backtest
        type: dict
        object_schema: "{train_period: str, years: list of int, actual: list of float, predicted: list of float, mape_pct: float, notes_ja: str}"

  - function_name: get_external_forecast
    inputs:
      - arg_name: region
        type: str
    out:
      - arg_name: external
        type: list
        object_schema: "list of {region: str, growth_2030_vs_2025_pct: float, growth_2040_vs_2025_pct: float, growth_2050_vs_2025_pct: float, note: str}"

  - function_name: generate_executive_summary
    inputs:
      - arg_name: run_ids
        type: list
      - arg_name: audience
        type: str
    out:
      - arg_name: summary_markdown
        type: str
      - arg_name: download_path
        type: str

examples:
  - ベースシナリオで2050年までの世界の建機需要の見通しを見せて
  - 地域別に見て、2050年に向けて最も伸びるのはどこ？その理由は？
  - 脱炭素加速シナリオだと鉱山機械の需要はどう変わる？ベースと比べて
  - 銅価格が今後10年、年3%ずつ上がったら鉱山機械はどうなる？
  - 中国の投資比率がもっと早く下がったら、一般建機の需要はどうなる？
  - アフリカの伸びが大きすぎる気がする。なぜこの数字になるの？
  - アフリカは中古機の流入で新車需要が3割減ると想定して補正して。理由は「中古機輸入比率の高さ」、補正者は経営管理部
  - これまでに誰がどんな補正をしたか一覧で見せて
  - 2005年時点のデータだけで予測していたら、実績をどこまで読めていた？
  - 外部予測と比べて、このモデルの見通しはどこが違う？
  - 今日の議論を、社長報告用に1枚のサマリーにまとめて

frontend:
  type: multi-page
  pages:
    - "長期見通しダッシュボード - 地域×機種の需要推移（1995〜2050年、実績と予測を連続表示）、シナリオ切替、P10〜P90の幅、外部予測の重ね表示、2030/2040/2050年の要約カード"
    - "シナリオ比較 - 4シナリオと利用者が作った what-if の比較チャートと差分表。前提（成長率、資源価格、レバーL1〜L4）の調整パネルから再計算"
    - "要因分解 - 地域・国・機種を選ぶと、2025年から目標年への変化を主要ドライバーの寄与で分解表示。類似の過去事例（同じ所得水準の国）を並べて表示"
    - "過去検証 - 2005年までで学習したモデルの2006〜2025年予測と実績を地域別に比較"
    - "前提補正と判断履歴（HILP）- エージェントが検知した違和感の一覧、補正の入力フォーム（係数・開始年・移行年数・理由・補正者）、補正前後の比較、判断履歴の表"
    - "経営会議サマリー - 選んだシナリオと補正を反映した1枚サマリーのプレビューとダウンロード"
  requirements: >-
    全ページ日本語。画面右側に常時エージェントのチャットパネルを置き、チャットでの操作結果が各ページのチャートに反映されること。
    落ち着いたビジネス向けの配色（紺・グレー基調、シナリオごとに固定色）。台数は千台単位、成長率は2025年比の倍率で表示。
    画面下部に常時「需要はデモ用の架空データ。ドライバーは公開データ（世界銀行、Our World in Data）、将来前提は公開シナリオを参考にした設定値」と出典を表示。
    実在企業のロゴや社名は画面に表示しない。DataRobotへの予測リクエストに失敗した場合は、起動時に作成したキャッシュ結果で表示を継続し、その旨を小さく表示する。
    詳細は IMPLEMENTATION_NOTES.md に従う。
