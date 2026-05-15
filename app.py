"""
Baseball WPA - リアルタイム勝率予測
SPAIAのテキストを貼り付けるだけで勝率グラフを表示
"""

import re
import math
import streamlit as st
import plotly.graph_objects as go

# =====================
# ページ設定
# =====================
st.set_page_config(
    page_title="Baseball WPA",
    page_icon="⚾",
    layout="wide",
)

st.markdown("""
<style>
  /* 全体背景 */
  .stApp, .stMain, section[data-testid="stSidebar"] {
      background-color: #0d0d14 !important;
  }
  /* テキスト */
  html, body, [class*="css"], p, label, span, div {
      color: #e8e8f0 !important;
  }
  /* テキストエリア */
  textarea {
      background-color: #13131a !important;
      color: #e8e8f0 !important;
      border: 1px solid #2a2a3e !important;
      border-radius: 8px !important;
      font-size: 12px !important;
  }
  /* ボタン */
  .stButton > button {
      background: #7c6af5 !important;
      color: white !important;
      border: none !important;
      border-radius: 8px !important;
      font-weight: 600 !important;
      padding: 10px 24px !important;
  }
  .stButton > button:hover {
      background: #6a5aed !important;
  }
  /* インプット */
  input[type="text"] {
      background-color: #13131a !important;
      color: #e8e8f0 !important;
      border: 1px solid #2a2a3e !important;
  }
  /* メトリクス */
  [data-testid="stMetricValue"] {
      font-size: 28px !important;
      font-weight: 700 !important;
      font-family: monospace !important;
  }
  /* 区切り線 */
  hr { border-color: #2a2a3e !important; }
</style>
""", unsafe_allow_html=True)


# =====================
# パーサー
# =====================

def parse_runners(text):
    r1 = r2 = r3 = '0'
    if '走者なし' in text or 'ランナーなし' in text:
        return '000'
    if '満塁' in text:
        return '111'
    if '一三塁' in text: r1 = r3 = '1'
    elif '二三塁' in text: r2 = r3 = '1'
    elif '一二塁' in text: r1 = r2 = '1'
    else:
        if '一塁' in text: r1 = '1'
        if '二塁' in text: r2 = '1'
        if '三塁' in text: r3 = '1'
    return r1 + r2 + r3


def parse_outs_label(text):
    for label, n in {'無死': 0, '一死': 1, '二死': 2}.items():
        if label in text:
            return n
    return 0


def parse_outs_number(text):
    m = re.search(r'(\d)アウト', text)
    return int(m.group(1)) if m else None


def parse_score(text):
    """どのチーム略称にも対応。ホームスコアを左として返す。"""
    m = re.search(
        r'[\u30A0-\u30FF\u3040-\u309F\u4E00-\u9FFF]{1,6}'
        r'\s+(\d+)-(\d+)\s+'
        r'[\u30A0-\u30FF\u3040-\u309F\u4E00-\u9FFF]{1,6}',
        text
    )
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def is_skip_line(text):
    keywords = [
        'けん制', '守備交代', '投手交代', 'コーチマウンド',
        'ピッチャー', '守備変更', 'マウンドにあがる',
        'ページトップ', '得点：', 'ヒット：', '四死球：',
        '→代打', '→代走',
    ]
    return any(k in text for k in keywords)


def is_at_bat_end(text):
    if text.endswith(('ストライク', 'ボール', 'ファウル')):
        return False
    if re.search(r'\d-\d\s*$', text):
        return False
    keywords = [
        'アウト', '三振', 'ヒット', '安打', 'ツーベース', '二塁打',
        'スリーベース', '三塁打', 'ホームラン', 'フォアボール', '四球',
        '死球', '犠牲フライ', 'ゲッツー', 'ダブルプレー',
        '盗塁失敗', '走塁死', '試合終了',
    ]
    return any(k in text for k in keywords)


def detect_teams(text):
    """テキストから先攻・後攻チーム名を自動検出"""
    away = '不明'
    home = '不明'
    m_away = re.search(r'1回表\s+(.+?)の攻撃', text)
    m_home = re.search(r'1回裏\s+(.+?)の攻撃', text)
    if m_away:
        away = m_away.group(1).strip()
    if m_home:
        home = m_home.group(1).strip()
    return home, away


def parse_game(text, home_team='ホーム', away_team='アウェイ'):
    """SPAIAテキスト → 打席リストに変換"""
    at_bats = []
    pattern = r'(\d+回(?:表|裏)\s+(?:.*?)の攻撃)'
    blocks = re.split(pattern, text)

    score_home = 0
    score_away = 0

    i = 1
    while i < len(blocks) - 1:
        header = blocks[i].strip()
        body   = blocks[i + 1] if i + 1 < len(blocks) else ''
        i += 2

        m = re.match(r'(\d+)回(表|裏)', header)
        if not m:
            continue

        inning = int(m.group(1))
        half   = m.group(2)

        # 打席ブロック分割
        ab_texts = re.split(r'\n\d+\.\n', '\n' + body)
        ab_texts = [a.strip() for a in ab_texts if a.strip()]

        for ab_text in ab_texts:
            lines = [l.strip() for l in ab_text.split('\n') if l.strip()]
            if not lines:
                continue

            # ヘッダー解析
            idx = 0
            batter_name = '不明'

            if idx < len(lines) and re.match(r'\d+番', lines[idx]):
                idx += 1
            elif idx < len(lines) and '代打' in lines[idx]:
                idx += 1

            if idx < len(lines) and not re.match(r'^\d+$', lines[idx]):
                batter_name = lines[idx].strip()
                idx += 1

            situation = ''
            if idx < len(lines) and re.match(r'(無死|一死|二死)', lines[idx]):
                situation = lines[idx]
                idx += 1

            outs_before    = parse_outs_label(situation)
            runners_before = parse_runners(situation)
            outs_after     = outs_before
            runners_after  = runners_before
            score_home_at_start = score_home
            score_away_at_start = score_away

            all_lines = lines[idx:]
            for line_idx, line in enumerate(all_lines):
                # スコア更新
                sh, sa = parse_score(line)
                if sh is not None:
                    score_home, score_away = sh, sa

                if is_skip_line(line):
                    continue
                if re.match(r'^\d+$', line):
                    continue

                if is_at_bat_end(line):
                    n = parse_outs_number(line)
                    if n is not None:
                        outs_after = n
                    new_r = parse_runners(line)
                    if any(c == '1' for c in new_r) or 'なし' in line:
                        runners_after = new_r
                    # 次の行のスコアを先読み
                    for next_line in all_lines[line_idx + 1: line_idx + 4]:
                        sh, sa = parse_score(next_line)
                        if sh is not None:
                            score_home, score_away = sh, sa
                            break
                    break

            at_bats.append({
                'inning':         inning,
                'half':           half,
                'batter':         batter_name,
                'outs_before':    outs_before,
                'runners_before': runners_before,
                'outs_after':     outs_after,
                'runners_after':  runners_after,
                'score_home_before': score_home_at_start,
                'score_away_before': score_away_at_start,
                'score_home_after':  score_home,
                'score_away_after':  score_away,
            })

    return at_bats, score_home, score_away


# =====================
# 勝率計算
# =====================

def detect_total_innings(at_bats):
    """延長を含む最大イニングを自動検出"""
    if not at_bats:
        return 9
    max_inning = max(ab['inning'] for ab in at_bats)
    return max(9, max_inning)


def win_prob(inning, half, outs, score_diff, total_innings=9):
    """
    スコア差・イニング・アウト数から勝率を計算（ホームチーム視点）
    延長戦にも対応。
    """
    if half == '表':
        remaining = (total_innings - inning) * 2 + 2
    else:
        remaining = (total_innings - inning) * 2 + 1

    remaining = max(remaining, 0)

    # 延長戦: 残り少ない場面なのでスコア差の影響を強める
    base_denominator = max(total_innings, 9) * 2
    progress = 1 - remaining / base_denominator

    # 延長は特に終盤感が強い → k を高めに
    if inning > 9:
        k = 2.0 + (inning - 9) * 0.2
    else:
        k = 0.4 + progress * 1.8

    x = score_diff * k
    prob = 1 / (1 + math.exp(-x))

    # 延長同点は50%に近づける
    if score_diff == 0:
        prob = 0.5

    return round(min(0.97, max(0.03, prob)), 4)


# =====================
# サイドバー
# =====================

with st.sidebar:
    st.markdown("## ⚾ Baseball WPA")
    st.markdown("---")
    st.markdown("### チーム設定")
    st.caption("テキストを貼ると自動検出されます")
    home_team = st.text_input("ホームチーム（1回裏）", value="")
    away_team = st.text_input("アウェイチーム（1回表）", value="")
    st.markdown("---")
    st.markdown("""
    **使い方**
    1. SPAIAの試合詳細を開く
    2. 全打席を展開してコピー
    3. 右の入力欄に貼り付け
    4. パース実行ボタンを押す
    """)


# =====================
# メイン
# =====================

st.markdown("# ⚾ リアルタイム勝率予測")
st.markdown("---")

raw_text = st.text_area(
    "SPAIAのテキストを貼り付け",
    height=200,
    placeholder="1回表 ○○の攻撃\n1.\n1番\n選手名\n無死走者なし\n...",
)

run_btn = st.button("⚡ パース実行", type="primary")

if run_btn:
    if not raw_text.strip():
        st.warning("テキストを貼り付けてください")
        st.stop()

    with st.spinner("解析中..."):
        # チーム名自動検出（手動入力が空の場合）
        auto_home, auto_away = detect_teams(raw_text)
        if not home_team.strip():
            home_team = auto_home
        if not away_team.strip():
            away_team = auto_away

        at_bats, final_home, final_away = parse_game(
            raw_text,
            home_team=home_team,
            away_team=away_team,
        )

    if not at_bats:
        st.error("データを読み取れませんでした。テキストを確認してください。")
        st.stop()

    st.success(f"✅ {len(at_bats)} 打席を解析しました")

    # スコア表示
    col1, col2, col3 = st.columns([2, 1, 2])
    with col1:
        st.metric(away_team, final_away)
    with col2:
        st.markdown("<div style='text-align:center;font-size:28px;padding-top:12px;color:#5a5a7a'>—</div>", unsafe_allow_html=True)
    with col3:
        st.metric(home_team, final_home)

    st.markdown("---")

    # 勝率計算
    total_innings = detect_total_innings(at_bats)  # 延長を自動検出
    wp_list  = []
    labels   = []
    tooltips = []

    for ab in at_bats:
        diff = ab['score_home_before'] - ab['score_away_before']
        wp   = win_prob(ab['inning'], ab['half'], ab['outs_before'], diff, total_innings)
        wp_list.append(wp)
        labels.append(f"{ab['inning']}回{ab['half']} {ab['batter']}")
        tooltips.append(
            f"{ab['inning']}回{ab['half']}<br>"
            f"打者: {ab['batter']}<br>"
            f"スコア: {ab['score_away_before']}-{ab['score_home_before']}<br>"
            f"{ab['outs_before']}死 {ab['runners_before']}<br>"
            f"勝率: {wp*100:.1f}%"
        )

    # イニング区切り
    inning_marks = []
    seen = set()
    for i, ab in enumerate(at_bats):
        key = (ab['inning'], ab['half'])
        if key not in seen:
            inning_marks.append((i, f"{ab['inning']}回{ab['half']}"))
            seen.add(key)

    # グラフ描画
    fig = go.Figure()

    # 背景塗り分け（ホーム優勢=赤 / アウェイ優勢=青）
    x_all = list(range(len(wp_list)))

    fig.add_trace(go.Scatter(
        x=x_all,
        y=wp_list,
        fill='tozeroy',
        fillcolor='rgba(124, 106, 245, 0.12)',
        line=dict(color='#7c6af5', width=2.5),
        mode='lines+markers',
        marker=dict(
            size=7,
            color=wp_list,
            colorscale=[[0, '#3b82f6'], [0.5, '#7c6af5'], [1, '#c8102e']],
            line=dict(color='#0d0d14', width=1),
        ),
        text=tooltips,
        hovertemplate='%{text}<extra></extra>',
        name='勝率',
    ))

    # 50%ライン
    fig.add_hline(
        y=0.5,
        line_dash='dash',
        line_color='#2a2a3e',
        line_width=1.5,
    )

    # イニング区切り線＋ラベル
    for idx, label in inning_marks:
        fig.add_vline(
            x=idx,
            line_color='#1e1e2e',
            line_width=1,
        )
        fig.add_annotation(
            x=idx,
            y=1.06,
            text=label,
            showarrow=False,
            font=dict(size=9, color='#5a5a7a'),
            yref='paper',
            xanchor='left',
        )

    # WPA変動が大きかった打席にマーク
    for i in range(1, len(wp_list)):
        delta = wp_list[i] - wp_list[i - 1]
        if abs(delta) >= 0.08:
            color = '#22c55e' if delta > 0 else '#f87171'
            fig.add_annotation(
                x=i,
                y=wp_list[i],
                text='▲' if delta > 0 else '▼',
                showarrow=False,
                font=dict(size=12, color=color),
                yshift=14,
            )

    fig.update_layout(
        title=dict(
            text=f'{away_team} vs {home_team} — 勝率推移',
            font=dict(size=16, color='#e8e8f0'),
            x=0.02,
        ),
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            title='打席',
            color='#5a5a7a',
            tickfont=dict(size=10),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor='#1a1a28',
            range=[0, 1],
            tickformat='.0%',
            title=f'{home_team} 勝率',
            color='#5a5a7a',
        ),
        plot_bgcolor='#0d0d14',
        paper_bgcolor='#0d0d14',
        font=dict(color='#e8e8f0'),
        height=500,
        margin=dict(t=60, b=40, l=60, r=20),
        showlegend=False,
        hovermode='x unified',
    )

    st.plotly_chart(fig, use_container_width=True)

    # 大きく動いた打席TOP5
    # WPA = 打席後の勝率 - 打席前の勝率
    # 打席前: その打席の開始スコアで計算
    # 打席後: その打席の終了スコアで計算
    st.markdown("### 勝率が大きく動いた打席")
    impacts = []
    for i, ab in enumerate(at_bats):
        diff_before = ab['score_home_before'] - ab['score_away_before']
        diff_after  = ab['score_home_after']  - ab['score_away_after']
        wp_before = win_prob(ab['inning'], ab['half'], ab['outs_before'], diff_before, total_innings)
        wp_after  = win_prob(ab['inning'], ab['half'], ab['outs_after'],  diff_after,  total_innings)
        delta = wp_after - wp_before
        impacts.append((abs(delta), delta, ab, i))
    impacts.sort(key=lambda x: x[0], reverse=True)

    for rank, (_, delta, ab, i) in enumerate(impacts[:5], 1):
        icon  = "📈" if delta > 0 else "📉"
        color = "#22c55e" if delta > 0 else "#f87171"
        score_before = f"{ab['score_away_before']}-{ab['score_home_before']}"
        score_after  = f"{ab['score_away_after']}-{ab['score_home_after']}"
        st.markdown(
            f"**{rank}.** {icon} "
            f"`{ab['inning']}回{ab['half']}` "
            f"**{ab['batter']}** "
            f"スコア:{score_before}→{score_after} "
            f"<span style='color:{color};font-family:monospace;font-weight:700'>{delta:+.1%}</span>",
            unsafe_allow_html=True,
        )
