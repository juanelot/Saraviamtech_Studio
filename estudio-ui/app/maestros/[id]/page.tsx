import FichaMaestro from "@/components/FichaMaestro";

export default async function Pagina({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <FichaMaestro id={id} />;
}
