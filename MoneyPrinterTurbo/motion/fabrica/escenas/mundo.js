// Escena MUNDO: un mundo 3D (three.js) que se va armando y que la camara recorre. Lo dibuja mundo3d.js (modulo:
// necesita el importmap que Python pone en la cabeza); aqui solo se espera a que este listo.
// ESCENA.mundo = { cosas: [...], tomas: [...], iconos: {nombre: svg} } (ver mundo3d.js)
F.montar(() => {
  F.esperar(import("./mundo3d.js").then((m) => m.montar(F)));
});
