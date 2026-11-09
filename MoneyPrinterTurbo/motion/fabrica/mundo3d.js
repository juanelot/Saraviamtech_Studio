// Mundo 3D de la Fabrica (three.js, MIT): un solo escenario que se arma escena tras escena. Python reparte las cosas
// por el escenario (x, z en metros, hacia el fondo) y decide las tomas; aqui solo se pinta cada cuadro en funcion del
// tiempo (pintar(t)), asi HyperFrames saca siempre lo mismo.
//
// ESCENA.mundo = {
//   cosas: [{ id, icono?: nombre Phosphor | modelo?: "caja", color: COLOR o #hex, x, z, tam,
//             a: segundo en que entra (< 0: ya estaba), gris: segundo desde el que va gris (null: nunca),
//             golpes: [segundos en que se vuelve a nombrar: da un saltito] }],
//   tomas: [{ t, cosas: [ids que deben verse], az, el (grados), lejos (1 = justo), fov, deriva (grados/s) }],
//   iconos: { nombre: "<svg ...>" }
// }
import * as THREE from "three";
import { SVGLoader } from "three/addons/SVGLoader.js";

const lim = (x) => Math.min(1, Math.max(0, x));
const suave = (x) => (x = lim(x), x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const rebote = (x) => { x = lim(x); const c1 = 1.9, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
const mezcla = (a, b, k) => a + (b - a) * k;
const TRANSICION = 0.85;   // s que tarda la camara de una toma a otra
const RADIO = 0.85;        // lo que ocupa cada cosa al encuadrar (m)

// un icono Phosphor (relleno) extruido: se lee de frente, asi que siempre mira a la camara
function icono3D(svg, color, tam) {
  const datos = new SVGLoader().parse(svg);
  const formas = datos.paths.flatMap((p) => SVGLoader.createShapes(p));
  const geo = new THREE.ExtrudeGeometry(formas, { depth: 64, bevelEnabled: true, bevelThickness: 7, bevelSize: 5,
                                                   bevelSegments: 3, curveSegments: 14 });
  geo.scale(1, -1, 1);   // el SVG va con la y hacia abajo
  geo.computeBoundingBox();
  const b = geo.boundingBox;
  geo.translate(-(b.min.x + b.max.x) / 2, -b.min.y, -(b.min.z + b.max.z) / 2);
  geo.computeVertexNormals();
  const mat = new THREE.MeshPhysicalMaterial({ color, roughness: 0.32, clearcoat: 0.6, clearcoatRoughness: 0.25,
                                               emissive: color, emissiveIntensity: 0.12 });
  const malla = new THREE.Mesh(geo, mat);
  malla.scale.setScalar(tam / Math.max(b.max.x - b.min.x, b.max.y - b.min.y));
  malla.castShadow = malla.receiveShadow = true;
  malla.userData.materiales = [mat];
  malla.userData.mira = true;
  return malla;
}

// caja de carton cerrada con su cinta (el protagonista tipico de envios, compras, mudanzas)
function caja3D(color, tam) {
  const g = new THREE.Group();
  const carton = new THREE.MeshPhysicalMaterial({ color, roughness: 0.75, clearcoat: 0.15 });
  const s = tam / 1.15;
  const cuerpo = new THREE.Mesh(new THREE.BoxGeometry(1.15 * s, 0.82 * s, 0.9 * s), carton);
  cuerpo.position.y = 0.41 * s;
  cuerpo.castShadow = cuerpo.receiveShadow = true;
  const raya = new THREE.Mesh(new THREE.BoxGeometry(1.155 * s, 0.006, 0.9 * s), new THREE.MeshStandardMaterial({ color: "#000", transparent: true, opacity: 0.25 }));
  raya.position.y = 0.82 * s;
  const cinta = new THREE.Mesh(new THREE.BoxGeometry(0.22 * s, 0.012, 0.92 * s), new THREE.MeshStandardMaterial({ color: "#f0d9a8", roughness: 0.4 }));
  cinta.position.y = 0.826 * s;
  g.add(cuerpo, raya, cinta);
  g.userData.materiales = [carton];
  return g;
}
const MODELOS = { caja: caja3D };

export function montar(F) {
  const { W, H } = F;
  const M = (F.E && F.E.mundo) || { cosas: [], tomas: [] };
  const color = (c) => (/^#[0-9a-f]{6}$/i.test(c || "") ? c : F.v(c || "acento") || F.v("acento"));
  const FONDO = new THREE.Color(F.v("fondo") || "#141414");
  const PISO = new THREE.Color(F.v("fondo-2") || "#222").lerp(FONDO, 0.35);
  const claro = FONDO.getHSL({}).l > 0.5;
  const GRIS = new THREE.Color(claro ? "#b9b4ad" : "#5d5752");

  // el lienzo va detras de todo lo demas de la escena (subtitulos, extras)
  const lienzo = F.crear("canvas");
  lienzo.width = W; lienzo.height = H;
  lienzo.style.cssText = "position:absolute;inset:0;width:100%;height:100%;";
  F.escena.prepend(lienzo);

  const renderer = new THREE.WebGLRenderer({ canvas: lienzo, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = claro ? 1.0 : 1.3;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const escena = new THREE.Scene();
  escena.background = FONDO;
  escena.fog = new THREE.Fog(FONDO, 16, 42);
  const camara = new THREE.PerspectiveCamera(34, W / H, 0.1, 200);

  escena.add(new THREE.HemisphereLight("#fff0dd", claro ? "#9a8f80" : "#3a2416", claro ? 1.6 : 1.1));
  const sol = new THREE.DirectionalLight("#fff1dc", claro ? 2.4 : 3.6);
  sol.castShadow = true;
  sol.shadow.mapSize.set(2048, 2048);
  Object.assign(sol.shadow.camera, { left: -8, right: 8, top: 8, bottom: -8, near: 1, far: 40 });
  sol.shadow.radius = 6;
  sol.shadow.bias = -0.0004;
  escena.add(sol, sol.target);
  const relleno = new THREE.DirectionalLight("#cfe0ff", 0.9);    // relleno frio de frente: lo azul no se apaga
  const contra = new THREE.DirectionalLight(F.v("acento") || "#ff9a3c", claro ? 0.8 : 1.6);   // contraluz con el color del estilo
  escena.add(relleno, contra);

  const piso = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), new THREE.MeshStandardMaterial({ color: PISO, roughness: 0.92 }));
  piso.rotation.x = -Math.PI / 2;
  piso.receiveShadow = true;
  escena.add(piso);
  // lineas del color de acento en el piso: dan escala y profundidad
  const linea = new THREE.MeshStandardMaterial({ color: F.v("acento") || "#c8952e", emissive: F.v("acento") || "#6b4710",
                                                 emissiveIntensity: 0.35, roughness: 0.4, metalness: 0.4 });
  for (const [x, z, giro] of [[-1, -6, 0.5], [2, -12, -0.35], [-5, 3, -0.6], [4, -2, 0.9], [-3, -18, 0.2]]) {
    const l = new THREE.Mesh(new THREE.BoxGeometry(40, 0.012, 0.035), linea);
    l.position.set(x, 0.006, z); l.rotation.y = giro; escena.add(l);
  }

  // las cosas, cada una en su pedestal
  const pedestal = new THREE.CylinderGeometry(0.95, 1.0, 0.1, 64);
  const matPed = new THREE.MeshStandardMaterial({ color: PISO.clone().lerp(new THREE.Color(claro ? "#000" : "#fff"), 0.08), roughness: 0.7 });
  const cosas = {};
  for (const c of M.cosas) {
    const hecho = c.modelo && MODELOS[c.modelo];
    const svg = c.icono && M.iconos && M.iconos[c.icono];
    if (!hecho && !svg) continue;
    const obj = hecho ? MODELOS[c.modelo](color(c.color), c.tam || 1.2) : icono3D(svg, color(c.color), c.tam || 1.25);
    obj.position.y = 0.1;
    const ped = new THREE.Mesh(pedestal, matPed);
    ped.position.y = 0.05; ped.castShadow = ped.receiveShadow = true;
    const grupo = new THREE.Group();
    grupo.add(ped, obj);
    grupo.position.set(c.x, 0, c.z);
    escena.add(grupo);
    const mats = obj.userData.materiales;
    cosas[c.id] = { ...c, grupo, obj, mats, bases: mats.map((m) => m.color.clone()) };
  }

  // encuadre: la distancia justa para que las cosas de la toma quepan en la zona segura (F.zona: arriba los
  // subtitulos no estorban), medida en el sistema de la camara (asi lo que esta en fila hacia el fondo cabe)
  const z = F.zona;
  const zx = z.w / W, zy = z.h / H;                  // que parte del cuadro es la zona
  const cy = (z.y + z.h / 2) / H;                    // donde cae su centro (0 arriba, 1 abajo)
  const encuadra = (tm) => {
    const pts = (tm.cosas || []).map((id) => cosas[id]).filter(Boolean).map((c) => new THREE.Vector3(c.x, 0.55, c.z));
    if (!pts.length) pts.push(new THREE.Vector3(0, 0.55, 0));
    const centro = pts.reduce((a, b) => a.clone().add(b), new THREE.Vector3()).multiplyScalar(1 / pts.length);
    const az = (tm.az * Math.PI) / 180, el = (tm.el * Math.PI) / 180;
    const atras = new THREE.Vector3(Math.cos(el) * Math.sin(az), Math.sin(el), Math.cos(el) * Math.cos(az));
    const derecha = new THREE.Vector3(0, 1, 0).cross(atras).normalize();
    const arriba = atras.clone().cross(derecha).normalize();
    const vfov = ((tm.fov || 34) * Math.PI) / 180;
    const tv = Math.tan(vfov / 2) * zy, th = Math.tan(vfov / 2) * (W / H) * zx;
    let d = 2;
    for (const q of pts) {
      const r = q.clone().sub(centro);
      const hondo = -r.dot(atras);                   // lo que esta mas lejos de la camara que el centro
      d = Math.max(d, (Math.abs(r.dot(derecha)) + RADIO) / th - hondo, (Math.abs(r.dot(arriba)) + RADIO * 0.9) / tv - hondo);
    }
    return { ...tm, mira: [centro.x, centro.y, centro.z], d: d * (tm.lejos || 1), fov: tm.fov || 34, deriva: tm.deriva || 0 };
  };
  // el centro de la imagen baja al centro de la zona segura
  camara.setViewOffset(W, H, 0, (0.5 - cy) * H, W, H);
  const tomas = (M.tomas.length ? M.tomas : [{ t: 0, cosas: Object.keys(cosas), az: -20, el: 25, lejos: 1 }]).map(encuadra);

  const plano = (t) => {
    let i = 0;
    while (i + 1 < tomas.length && t >= tomas[i + 1].t) i++;
    const p = tomas[i];
    const q = { ...p, az: p.az + p.deriva * (t - p.t) };
    if (i === 0) return q;
    const a = tomas[i - 1];
    const antes = { ...a, az: a.az + a.deriva * (p.t - a.t) };
    const k = suave((t - p.t) / TRANSICION);
    return { mira: antes.mira.map((v, j) => mezcla(v, q.mira[j], k)), az: mezcla(antes.az, q.az, k),
             el: mezcla(antes.el, q.el, k), d: mezcla(antes.d, q.d, k), fov: mezcla(antes.fov, q.fov, k) };
  };

  const tmp = new THREE.Color();
  const pintar = (t) => {
    const p = plano(t);
    const az = (p.az * Math.PI) / 180, el = (p.el * Math.PI) / 180;
    for (const c of Object.values(cosas)) {
      const k = lim((t - c.a) / 0.55);
      c.grupo.visible = t >= c.a;
      c.grupo.scale.setScalar(Math.max(0.0001, c.a < 0 ? 1 : rebote(k)));
      const entrada = c.a < 0 ? 0 : (1 - suave(k)) * -0.9;
      const vaiven = Math.sin(t * 1.3 + c.x * 2) * 0.1;
      c.obj.rotation.y = (c.obj.userData.mira ? az : -0.45) + entrada + vaiven;
      // al volver a nombrarla da un saltito
      let y = 0.1;
      for (const g of c.golpes || []) {
        const e = (t - g) / 0.4;
        if (e > 0 && e < 1) y += Math.sin(Math.PI * e) * 0.22;
      }
      c.obj.position.y = y;
      const g = c.gris == null ? 0 : c.gris < 0 ? 1 : suave((t - c.gris) / 0.6);
      c.mats.forEach((m, j) => m.color.copy(tmp.copy(c.bases[j]).lerp(GRIS, g * 0.8)));
    }
    camara.fov = p.fov;
    camara.position.set(p.mira[0] + p.d * Math.cos(el) * Math.sin(az), p.mira[1] + p.d * Math.sin(el),
                        p.mira[2] + p.d * Math.cos(el) * Math.cos(az));
    camara.lookAt(p.mira[0], p.mira[1], p.mira[2]);
    camara.updateProjectionMatrix();
    // las luces siguen a la camara: la sombra cae siempre bien encuadrada
    sol.position.set(p.mira[0] - 4, 9, p.mira[2] + 6);
    sol.target.position.set(p.mira[0], 0, p.mira[2]);
    relleno.position.set(camara.position.x, camara.position.y + 2, camara.position.z);
    contra.position.set(p.mira[0] + 5, 4, p.mira[2] - 8);
    renderer.render(escena, camara);
  };
  F.alPintar(pintar);
  pintar(0);
}
