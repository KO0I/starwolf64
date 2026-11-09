import json
import pathlib


def write_catalog(manifest: dict, destination: pathlib.Path) -> None:
    """Write an offline listening catalog for the exported samples and sequences."""
    destination.mkdir(parents=True, exist_ok=True)
    index_path = destination / "index.html"

    raw_json = json.dumps(manifest, ensure_ascii=False)
    safe_json = raw_json.replace("<", "\\u003c")

    css = """
    body {font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:1rem;}
    .table-wrap {overflow-x:auto;}
    input,select {font:inherit;padding:.4rem;background:#222;color:#eee;border:1px solid #666;}
    label {display:inline-block;margin:.4rem 1rem .4rem 0;}
    audio {width:260px;}
    td {overflow-wrap:anywhere;}
    h1 {font-size:1.6rem;}
    .filter {margin-bottom:1rem;}
    table {width:100%;border-collapse:collapse;}
    th,td {padding:0.4rem;border:1px solid #333;}
    th {background:#222;}
    tr:nth-child(even){background:#1a1a1a;}
    a {color:#4ea;}
    .status {margin-top:1rem;font-size:0.9rem;color:#aaa;}
    button{background:#333;color:#eee;border:none;padding:0.3rem 0.6rem;cursor:pointer;}
    button:hover{background:#444;}
    """

    js = """
    const manifest = JSON.parse(document.getElementById('manifest').textContent);
    const samples = manifest.samples || [];
    const sequences = manifest.sequences || [];
    const pageSize = 50;
    let displayed = 0;
    let currentFilter = '';
    let currentCategory = '';

    function escapeHtml(str){return String(str).replace(/[&<>"]/g,function(s){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[s];});}

    function renderSamples(reset){
        const tbody = document.getElementById('samples-body');
        if(reset){tbody.innerHTML=''; displayed=0;}
        const filtered = samples.filter(s => {
            const categoryMatches = !currentCategory || s.category === currentCategory;
            const text = (s.resource + ' ' + s.wav + ' ' + s.soundfont_ids.join(' ')).toLowerCase();
            return categoryMatches && (!currentFilter || text.includes(currentFilter));
        });
        const fragment = document.createDocumentFragment();
        const end = Math.min(displayed + pageSize, filtered.length);
        for (; displayed < end; displayed++) {
            const s = filtered[displayed];
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${escapeHtml(s.resource)}<br><small>${escapeHtml(s.category)}</small></td>
                <td><a href="${escapeHtml(s.wav)}" download>Download WAV</a></td>
                <td>${s.duration_seconds.toFixed(2)}s @ ${s.sample_rate}Hz</td>
                <td>${s.soundfont_ids.join(', ')}</td>
                <td><audio controls preload="none" src="${escapeHtml(s.wav)}"></audio></td>
            `;
            fragment.appendChild(tr);
        }
        tbody.appendChild(fragment);
        document.getElementById('load-more').hidden = displayed >= filtered.length;
        document.getElementById('status').textContent =
            `Showing ${displayed} of ${filtered.length} matching samples. ${samples.length} samples total.`;
    }

    function renderSequences(){
        const tbody = document.getElementById('seq-body');
        sequences.forEach(seq=>{
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${seq.id}</td>
                <td>${escapeHtml(seq.names.join(', '))}</td>
                <td>${escapeHtml(seq.resource)}</td>
                <td><a href="${escapeHtml(seq.file)}" download>${escapeHtml(seq.file)}</a></td>
                <td>${seq.size}</td>
                <td>${seq.soundfont_ids.join(', ')}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    function init(){
        // Category dropdown
        const catSelect = document.getElementById('category-select');
        const categories = Array.from(new Set(samples.map(s=>s.category))).sort();
        categories.forEach(c=>{const opt=document.createElement('option');opt.value=c;opt.textContent=c;catSelect.appendChild(opt);});
        catSelect.addEventListener('change',()=>{currentCategory=catSelect.value; renderSamples(true);});

        // Search input
        const searchInput = document.getElementById('search-input');
        searchInput.addEventListener('input',()=>{currentFilter=searchInput.value.toLowerCase(); renderSamples(true);});

        // Load more button
        document.getElementById('load-more').addEventListener('click',()=>{renderSamples(false);});

        // Ensure only one audio plays
        document.addEventListener('play',function(e){
            const audios = document.getElementsByTagName('audio');
            for(const a of audios){if(a!==e.target){a.pause();}}
        }, true);

        renderSamples(true);
        renderSequences();
    }

    window.addEventListener('DOMContentLoaded', init);
    """

    html_content = f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='UTF-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Starship audio export</title>
<style>{css}</style>
</head>
<body>
<h1>Starship audio export</h1>
<p>Original samples grouped by soundfont usage. Preview pitch follows instrument tuning. Voice message IDs are not mapped yet.</p>
<p><a href='audio-assets.zip' download>Download the complete export</a> · <a href='README.txt'>Export notes</a></p>
<div class='filter'>
  <label>Search <input type='search' id='search-input' placeholder='Resource or soundfont'></label>
  <label>Category <select id='category-select'><option value=''>All</option></select></label>
</div>
<div class='table-wrap'><table>
  <thead><tr><th>Resource</th><th>WAV</th><th>Duration / Rate</th><th>Soundfonts</th><th>Play</th></tr></thead>
  <tbody id='samples-body'></tbody>
</table></div>
<p class='status' id='status' aria-live='polite'></p>
<button id='load-more'>Load more</button>
<h2>Sequences</h2>
<p>.m64 files are raw sequence bytecode, not rendered audio.</p>
<div class='table-wrap'><table>
  <thead><tr><th>ID</th><th>Names</th><th>Resource</th><th>File</th><th>Size</th><th>Soundfonts</th></tr></thead>
  <tbody id='seq-body'></tbody>
</table></div>
<p>Links: <a href='manifest.json'>manifest.json</a> | <a href='inventory.csv'>inventory.csv</a> | <a href='original-resources/'>original-resources/</a> | <a href='audio-assets.zip'>audio-assets.zip</a></p>
<script id='manifest' type='application/json'>
{safe_json}
</script>
<script>{js}</script>
</body>
</html>
"""

    index_path.write_text(html_content, encoding='utf-8')
