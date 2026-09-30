import SerieMaestro from "@/components/SerieMaestro";

export default async function Pagina({ params }: { params: Promise<{ id: string; sid: string }> }) {
  const { id, sid } = await params;
  return <SerieMaestro id={id} sid={sid} />;
}
