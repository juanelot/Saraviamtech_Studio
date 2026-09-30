import CreacionMaestro from "@/components/CreacionMaestro";

export default async function Pagina({ params }: { params: Promise<{ id: string; cid: string }> }) {
  const { id, cid } = await params;
  return <CreacionMaestro id={id} cid={cid} />;
}
