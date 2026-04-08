import React, { useState, useEffect, useRef } from 'react';
import { motion, useMotionValue, useSpring } from 'framer-motion';
import Map, { Layer } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  Building2, ShieldCheck, Zap, Waves, FileDown, Globe2,
  Minus, GripHorizontal, Play
} from 'lucide-react';
import equinoxLogo from './assets/equinox-logo.png';
import cityRenderImg from './assets/city-render.png';
import './index.css';

const features = [
  { icon: <Globe2 />, title: "Smart City Planning", desc: "For urban and semi-urban regions" },
  { icon: <Building2 />, title: "Automated Layouts", desc: "Based on zoning & FSI rules" },
  { icon: <ShieldCheck />, title: "Real-time Compliance", desc: "Instant municipal regulation checks" },
  { icon: <Zap />, title: "Infrastructure Config", desc: "Water, drainage, electricity, & roads" },
  { icon: <Waves />, title: "Impact Simulation", desc: "Flood & environmental analysis using real data" },
  { icon: <FileDown />, title: "Export-Ready Plans", desc: "Gov submissions ready in PDF, CAD, & GIS" }
];



// SVG Component for the winding blue background line
const WindingLine = () => (
  <svg
    className="winding-line"
    viewBox="0 0 1000 2000"
    preserveAspectRatio="xMidYMid slice"
    fill="none"
  >
    <motion.path
      d="M -100 200 C 400 50, 900 600, 300 900 C -100 1100, 100 1600, 900 1800"
      stroke="#3b59f8"
      strokeWidth="45"
      strokeLinecap="round"
      initial={{ pathLength: 0 }}
      whileInView={{ pathLength: 1 }}
      viewport={{ once: false, margin: "-100px" }}
      transition={{ duration: 2.5, ease: "easeOut" }}
    />
  </svg>
);

function App() {
  const mapRef = useRef();

  const cursorX = useMotionValue(typeof window !== 'undefined' ? window.innerWidth / 2 : 500);
  const cursorY = useMotionValue(typeof window !== 'undefined' ? window.innerHeight / 2 : 400);

  const springConfig = { damping: 25, stiffness: 400, mass: 0.5 };
  const cursorXSpring = useSpring(cursorX, springConfig);
  const cursorYSpring = useSpring(cursorY, springConfig);

  useEffect(() => {
    const moveCursor = (e) => {
      cursorX.set(e.clientX);
      cursorY.set(e.clientY);
    };
    window.addEventListener("mousemove", moveCursor);
    return () => window.removeEventListener("mousemove", moveCursor);
  }, [cursorX, cursorY]);

  // Pointing map directly at San Francisco (Top Down to start)
  const [viewState, setViewState] = useState({
    longitude: -73.9857,
    latitude: 40.7484,
    zoom: 13.5,
    pitch: 0,
    bearing: 0
  });

  const [is3D, setIs3D] = useState(false);

  // Automatically trigger the massive cinematic 3D sweep 1.5 seconds after page load!
  useEffect(() => {
    const timer = setTimeout(() => {
      setIs3D(true);
    }, 1500);
    return () => clearTimeout(timer);
  }, []);

  // Watch for state changes and enact fast, cinematic FlyTo animations!
  useEffect(() => {
    if (mapRef.current) {
      if (is3D) {
        // FAST Sweep into 3D isometric simulation of Empire State Building
        mapRef.current.flyTo({
          center: [-73.9857, 40.7484],
          zoom: 14.5,
          pitch: 65,
          bearing: -20, // Sweeping angle to look through the dense skyscraper corridor
          duration: 1500, // Extremely fast! 1.5 seconds layout transition
          essential: true
        });
      } else {
        // FAST return to ground topography flat view
        mapRef.current.flyTo({
          center: [-73.9857, 40.7484],
          zoom: 13.5,
          pitch: 0,
          bearing: 0,
          duration: 1500, // 1.5 second immediate snapping pull out
          essential: true
        });
      }
    }
  }, [is3D]);

  return (
    <div className="lusion-app-container">
      <motion.div
        className="cursor-glow-light"
        style={{ x: cursorXSpring, y: cursorYSpring }}
      />

      <header className="lusion-header">
        <div className="lusion-logo">INFRONIX</div>
        <div className="header-aesthetic-text">
          "from city vision → into real infrastructure intelligence."
        </div>
        <div className="lusion-nav">
          <a href="/index" className="nav-btn-action" style={{ textDecoration: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>GET STARTED</a>
        </div>
      </header>

      <main className="lusion-main">
        <div
          className="lusion-canvas-container dark-mode"
          style={{ background: '#080A10' }}
        >
          <Map
            ref={mapRef}
            {...viewState}
            onMove={evt => setViewState(evt.viewState)}
            mapStyle="https://api.maptiler.com/maps/dataviz-dark/style.json?key=get_your_own_OpIi9ZULNHzrESv6T2vL"
            interactive={true}
            dragRotate={true}
            scrollZoom={false}
          >
            <Layer
              id="3d-buildings"
              source="maptiler_planet"
              source-layer="building"
              type="fill-extrusion"
              minzoom={13}
              paint={{
                'fill-extrusion-color': [
                  'interpolate',
                  ['linear'],
                  ['get', 'render_height'],
                  0, '#0F172A',
                  30, '#19507a',
                  80, '#2178ad',
                  150, '#2db2ff'
                ],
                'fill-extrusion-height': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  13.5, 0,
                  14.2, ['get', 'render_height']
                ],
                'fill-extrusion-base': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  13.5, 0,
                  14.2, ['get', 'render_min_height']
                ],
                'fill-extrusion-opacity': 0.85
              }}
            />
          </Map>
        </div>

        <div className="lusion-footer">
          <span>+</span>
          <span>+</span>
          <span className="scroll-text">SCROLL TO EXPLORE</span>
          <span>+</span>
          <span>+</span>
        </div>
      </main>

      {/* Dynamic Layered Scrolling Content */}
      <div className="lusion-content-section" style={{ background: '#f4f4f6', paddingTop: '8rem', paddingBottom: '10rem', position: 'relative', zIndex: 10 }}>
        <WindingLine />

        <section className="scroll-section massive-text-section">
          <motion.h1
            initial={{ y: 80, opacity: 0 }}
            whileInView={{ y: 0, opacity: 1 }}
            viewport={{ once: false, margin: "-200px" }}
            transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
          >
            Smart Planning,<br />Brought to Reality
          </motion.h1>
        </section>

        <section className="scroll-section split-section">
          <div className="left-column">
            <motion.div
              className="media-card blue-card-1"
              initial={{ y: 150, opacity: 0 }}
              whileInView={{ y: 0, opacity: 1 }}
              viewport={{ once: false, margin: "-10%" }}
              transition={{ duration: 1.2, ease: "easeOut" }}
              style={{ padding: '4rem 3rem', color: 'white', height: 'auto', minHeight: '600px' }}
            >
              <div className="card-mock-content"></div>
              <div style={{ position: 'relative', zIndex: 10 }}>
                <h2 style={{ fontSize: '2.2rem', fontWeight: 600, marginBottom: '3rem', letterSpacing: '-0.5px' }}>Core Platform</h2>
                {features.slice(0, 3).map((feat, idx) => (
                  <div key={idx} style={{ marginBottom: '2.5rem' }}>
                    <div style={{ color: 'white', marginBottom: '1rem', display: 'inline-block', background: 'rgba(255,255,255,0.2)', padding: '0.8rem', borderRadius: '14px' }}>{feat.icon}</div>
                    <h3 style={{ fontSize: '1.4rem', fontWeight: 600, margin: '0 0 0.4rem 0' }}>{feat.title}</h3>
                    <p style={{ fontSize: '1.05rem', color: 'rgba(255,255,255,0.8)', margin: 0, lineHeight: 1.4 }}>{feat.desc}</p>
                  </div>
                ))}
              </div>
            </motion.div>

            <motion.div
              className="media-card blue-card-2"
              initial={{ y: 150, opacity: 0 }}
              whileInView={{ y: 0, opacity: 1 }}
              viewport={{ once: false, margin: "-10%" }}
              transition={{ duration: 1.2, delay: 0.1, ease: "easeOut" }}
              style={{ padding: '4rem 3rem', color: 'white', height: 'auto', minHeight: '650px' }}
            >
              <div className="card-mock-content-2"></div>
              <div style={{ position: 'relative', zIndex: 10 }}>
                <h2 style={{ fontSize: '2.2rem', fontWeight: 600, marginBottom: '3rem', letterSpacing: '-0.5px' }}>Simulation</h2>
                {features.slice(3, 6).map((feat, idx) => (
                  <div key={idx} style={{ marginBottom: '2.5rem' }}>
                    <div style={{ color: 'white', marginBottom: '1rem', display: 'inline-block', background: 'rgba(255,255,255,0.2)', padding: '0.8rem', borderRadius: '14px' }}>{feat.icon}</div>
                    <h3 style={{ fontSize: '1.4rem', fontWeight: 600, margin: '0 0 0.4rem 0' }}>{feat.title}</h3>
                    <p style={{ fontSize: '1.05rem', color: 'rgba(255,255,255,0.8)', margin: 0, lineHeight: 1.4 }}>{feat.desc}</p>
                  </div>
                ))}
              </div>
            </motion.div>
          </div>

          <div className="right-column">
            <motion.p
              initial={{ y: 40, opacity: 0 }}
              whileInView={{ y: 0, opacity: 1 }}
              viewport={{ once: false, margin: "-50px" }}
              transition={{ duration: 0.8 }}
              className="desc-text"
            >
              We combine municipal compliance, motion, 3D simulations, and development to create digital infrastructure layouts that feel visually striking and technically seamless. From campaign launches to immersive brand worlds, we build work that captures attention and invites interaction.
            </motion.p>

              <motion.div
                initial={{ opacity: 0, y: 80 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: false, margin: "-10%" }}
                transition={{ duration: 1.2, delay: 0.1, ease: 'easeOut' }}
                style={{
                  marginTop: '6rem',
                  borderRadius: '24px',
                  overflow: 'hidden',
                  boxShadow: '0 40px 80px rgba(0, 0, 0, 0.08), 0 0 0 1px rgba(0,0,0,0.02)',
                  background: '#fff'
                }}
              >
                <img src={cityRenderImg} alt="Abstract City Isometric Layout" style={{ width: '100%', height: 'auto', display: 'block', transform: 'scale(1.02)' }} />
              </motion.div>
          </div>
        </section>
      </div>

      {/* Final Footer block mimicking the Lusion screenshot */}
      <footer className="final-dark-footer">
        <div className="footer-content" style={{ display: 'flex', justifyContent: 'flex-start', alignItems: 'flex-end', gap: '4rem', flexWrap: 'nowrap' }}>

          <div className="footer-about" style={{ maxWidth: '750px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '2rem', marginBottom: '3rem' }}>
              <h1 style={{ fontSize: '4.5rem', fontWeight: 300, letterSpacing: '-2px', margin: 0, color: '#fff' }}>ABOUT US</h1>
              <div style={{ height: '1px', width: '150px', background: 'linear-gradient(90deg, rgba(255,255,255,0.3) 0%, transparent 100%)' }}></div>
            </div>

            <h2 style={{ fontSize: '2.4rem', fontWeight: 400, letterSpacing: '-0.5px', lineHeight: '1.3', color: '#fff', margin: '0 0 2rem 0', maxWidth: '650px' }}>
              We are building the future of <span style={{ color: '#2db2ff' }}>urban planning.</span>
            </h2>

            <p style={{ fontSize: '1.15rem', lineHeight: '1.8', color: 'rgba(255,255,255,0.5)', margin: 0, paddingLeft: '1.5rem', borderLeft: '2px solid rgba(255,255,255,0.1)' }}>
              Team <strong style={{ color: '#fff', fontWeight: 500 }}>THE UNDERDOG</strong> presents <strong style={{ color: '#fff', fontWeight: 500 }}>INFRONIX</strong>, a technical platform that transforms raw land data into intelligent, compliant, and simulation-backed city layouts using AI — making planning radically faster, smarter, and more sustainable.
            </p>
          </div>

          <div className="equinox-label" style={{ textAlign: 'left', display: 'flex', flexDirection: 'column', alignItems: 'flex-start', marginBottom: '1rem' }}>
            <span style={{ marginBottom: '16px', display: 'block', fontSize: '1rem', color: '#aaa', letterSpacing: '2px', fontWeight: 500 }}>SUBMITTED TO</span>
            <img src={equinoxLogo} alt="EQUINOX" style={{ height: '110px', objectFit: 'contain' }} />
          </div>

        </div>
      </footer>

    </div>
  );
}

export default App;
