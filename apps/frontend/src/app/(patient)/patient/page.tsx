import { LabBookingConsentDemo } from "@/components/patient/LabBookingConsentDemo";
import { PageHeader } from "@/components/layout/PageHeader";

export default function PatientDashboardPage() {
  return (
    <>
      <PageHeader title="Welcome, Patient" />
      <LabBookingConsentDemo />
    </>
  );
}
