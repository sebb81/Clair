import {deviceLabels,type DeviceReport,type DeviceSelection} from './browser-generation'

export function DeviceStatus({preference,report}:{preference:DeviceSelection;report:DeviceReport|null}) {
  return <div className="device-status" aria-live="polite">
    <span>{report?`Dernier calcul WebNN : ${report.device.toUpperCase()} · génération validée`:`Calcul demandé : ${deviceLabels[preference]}`}</span>
    {report&&<details><summary>Détail du matériel et des replis</summary>
      <p>Choix : {deviceLabels[report.preference]}. {report.dispatches} exécutions WebNN pour le dernier appel.</p>
      {report.attempts.map((attempt,i)=><p key={i}>{attempt.device.toUpperCase()} : {attempt.status==='used'?'génération réussie':attempt.status==='skipped'?'échec déjà constaté dans cet onglet':'échec'}{attempt.error?` — ${attempt.error}`:''}</p>)}
      <p>Le contexte demandé a exécuté le modèle. Le navigateur ne confirme pas l’identité physique de la puce ni la répartition de toutes les opérations ; certaines peuvent rester sur CPU.</p>
    </details>}
  </div>
}
