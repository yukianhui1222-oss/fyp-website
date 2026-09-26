"""Code-native, decorative study illustration for the workspace landing page."""
import base64

HOME_HERO = """
<section class="glass-home-hero" aria-labelledby="home-title">
  <div class="glass-home-copy">
    <span class="home-brand-line"><span aria-hidden="true">✦</span> DOCUMIND · YOUR STUDY SPACE</span>
    <h1 id="home-title">Big ideas.<br><em>Clearer minds.</em></h1>
    <p>Turn your lecture notes into a little more clarity.<br>Summarize, connect and practice — all in one place.</p>
    <a class="home-upload-link" href="#home-upload">Start with your notes <span aria-hidden="true">↗</span></a>
    <div class="home-feature-pills"><span>Summaries</span><span>Mind maps</span><span>Practice</span></div>
  </div>
  <div class="glass-home-art" aria-hidden="true">
    <svg viewBox="0 0 500 400" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="book-cover" x2="1" y2="1"><stop stop-color="#a99cff"/><stop offset="1" stop-color="#6654c5"/></linearGradient>
        <linearGradient id="book-pages" x2="0" y2="1"><stop stop-color="#fff"/><stop offset="1" stop-color="#e0ddf7"/></linearGradient>
        <linearGradient id="mint-orb" x2="1" y2="1"><stop stop-color="#c1fff1"/><stop offset="1" stop-color="#43b3a4"/></linearGradient>
        <radialGradient id="purple-orb" cx=".3" cy=".2"><stop stop-color="#c4a9ff"/><stop offset="1" stop-color="#8254d4"/></radialGradient>
        <filter id="study-shadow" x="-50%" y="-50%" width="200%" height="220%"><feDropShadow dx="0" dy="14" stdDeviation="12" flood-color="#655293" flood-opacity=".2"/></filter>
      </defs>
      <circle cx="351" cy="98" r="66" fill="url(#purple-orb)"/>
      <circle cx="112" cy="242" r="46" fill="url(#mint-orb)"/>
      <circle cx="363" cy="297" r="74" fill="#f5d890" opacity=".7"/>
      <ellipse cx="254" cy="333" rx="144" ry="24" fill="#706399" opacity=".12"/>
      <g filter="url(#study-shadow)" transform="rotate(-9 245 240)">
        <path d="M126 179 Q184 159 245 190 Q302 159 366 179 L366 292 Q302 274 245 307 Q180 275 126 292Z" fill="url(#book-cover)"/>
        <path d="M136 169 Q190 151 245 181 Q302 151 356 169 L356 279 Q298 265 245 295 Q193 265 136 279Z" fill="url(#book-pages)"/>
        <path d="M245 182V294" stroke="#c4bddf" stroke-width="3"/>
        <path d="M154 199 Q190 194 225 210 M154 221 Q190 216 225 232 M154 244 Q190 239 215 250 M267 209 Q300 192 337 198 M267 233 Q300 216 337 222 M267 256 Q300 239 321 245" fill="none" stroke="#b9b0d7" stroke-width="6" stroke-linecap="round"/>
        <path d="M308 172V213L322 205L334 213V167" fill="#69c9ba"/>
      </g>
      <g filter="url(#study-shadow)" transform="rotate(-14 140 109)">
        <rect x="95" y="56" width="83" height="104" rx="17" fill="#ffffff" fill-opacity=".93"/>
        <rect x="112" y="76" width="29" height="30" rx="7" fill="#e2d8ff"/>
        <path d="M112 121H158 M112 134H144" stroke="#beb3da" stroke-width="5" stroke-linecap="round"/>
        <path d="M119 89L125 96L135 83" fill="none" stroke="#8c6acd" stroke-width="3" stroke-linecap="round"/>
      </g>
      <g filter="url(#study-shadow)" transform="rotate(12 393 203)">
        <rect x="354" y="163" width="83" height="72" rx="21" fill="#fff" fill-opacity=".92"/>
        <path d="M377 188L389 200L414 180" fill="none" stroke="#56b8a3" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M376 216H412" stroke="#c3e7df" stroke-width="5" stroke-linecap="round"/>
      </g>
      <g fill="#aa8ace"><path d="M228 63L233 76L246 81L233 86L228 99L223 86L210 81L223 76Z"/><path d="M411 273L415 282L424 286L415 290L411 299L407 290L398 286L407 282Z"/></g>
      <circle cx="80" cy="182" r="5" fill="#efb4cb"/><circle cx="302" cy="346" r="4" fill="#72c7b9"/>
    </svg>
    <span class="home-art-caption">A fresh perspective starts here.</span>
  </div>
</section>
"""

# Streamlit sanitizes inline SVG in st.html; an image preserves the vector art.
_svg_start = HOME_HERO.index('<svg ')
_svg_end = HOME_HERO.index('</svg>') + len('</svg>')
_svg_data = base64.b64encode(HOME_HERO[_svg_start:_svg_end].encode()).decode()
HOME_HERO = HOME_HERO[:_svg_start] + f'<img src="data:image/svg+xml;base64,{_svg_data}" alt="" width="500" height="400">' + HOME_HERO[_svg_end:]
