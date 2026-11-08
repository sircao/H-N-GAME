#include "ScientificEVRuntimeManager.h"
#include "StackelbergEVOptimizationModule.h"
#include "EngineUtils.h"
#include "HAL/PlatformMisc.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "String/LexFromString.h"

AScientificEVRuntimeManager::AScientificEVRuntimeManager() { PrimaryActorTick.bCanEverTick=true; }

void AScientificEVRuntimeManager::BeginPlay()
{
    Super::BeginPlay();
    FString Plan;
    FParse::Value(FCommandLine::Get(),TEXT("EVScientificPlan="),Plan);
    float ParsedSeconds=static_cast<float>(DaySeconds);
    FParse::Value(FCommandLine::Get(),TEXT("EVScientificSeconds="),ParsedSeconds);
    DaySeconds=ParsedSeconds;
    if (Plan.IsEmpty() || DaySeconds<=0 || !LoadPlan(Plan))
    {
        UE_LOG(LogStackelbergEV,Error,TEXT("Invalid scientific physical event contract. Legacy plans are not accepted."));
        SetActorTickEnabled(false); return;
    }
    int32 Bound=0;
    for (TActorIterator<AActor> It(GetWorld()); It; ++It)
        for (FVehicle& V:Vehicles)
            if (It->GetActorLabel().StartsWith(TEXT("EVSim_")+V.Id+TEXT("_"))) { V.Actor=*It; ++Bound; break; }
    if (Bound!=Vehicles.Num())
    {
        UE_LOG(LogStackelbergEV,Error,TEXT("Plan/scene mismatch: %d of %d vehicles; refusing partial service."),Bound,Vehicles.Num());
        SetActorTickEnabled(false); return;
    }
    for (TActorIterator<AActor> It(GetWorld()); It; ++It)
        if (It->GetClass()->GetName()==TEXT("EVTrafficRuntimeController")) It->SetActorTickEnabled(false);
    ObservationPath=FPaths::Combine(FPaths::GetPath(Plan),TEXT("unreal_observations.csv"));
    FParse::Value(FCommandLine::Get(),TEXT("EVScientificObservations="),ObservationPath);
    FFileHelper::SaveStringToFile(TEXT("sim_hour,vehicle_id,soc,battery_kwh,cumulative_traction_kwh,cumulative_grid_kwh,charging_kw,station_id,x_cm,y_cm,z_cm\n"),*ObservationPath);
    UpdateVehicles(); WriteSamples();
    UE_LOG(LogStackelbergEV,Display,TEXT("SCIENTIFIC_REPLAY_STARTED vehicles=%d output=%s"),Vehicles.Num(),*ObservationPath);
}

bool AScientificEVRuntimeManager::LoadPlan(const FString& Path)
{
    FString Text;
    if (!FFileHelper::LoadFileToString(Text,*Path)) return false;
    TArray<FString> Lines,Header;
    Text.ParseIntoArrayLines(Lines,true);
    if (Lines.Num()<2 || !ParseCsv(Lines[0],Header)) return false;
    TMap<FString,int32> Col;
    for (int32 I=0; I<Header.Num(); ++I) Col.Add(Header[I],I);
    const TCHAR* Required[]={TEXT("vehicle_id"),TEXT("task_id"),TEXT("event_type"),TEXT("start"),TEXT("end"),
        TEXT("deadline"),TEXT("energy_kwh"),TEXT("grid_kwh"),TEXT("path_points"),TEXT("station_id"),
        TEXT("initial_kwh"),TEXT("battery_kwh"),TEXT("terminal_kwh"),TEXT("efficiency")};
    for (const TCHAR* Name:Required) if (!Col.Contains(Name)) return false;
    TMap<FString,int32> Indices;
    for (int32 L=1; L<Lines.Num(); ++L)
    {
        TArray<FString> Fields;
        if (!ParseCsv(Lines[L],Fields) || Fields.Num()!=Header.Num()) return false;
        const auto Cell=[&](const TCHAR* Name)->const FString& { return Fields[Col[Name]]; };
        const auto Number=[&](const TCHAR* Name,double& Out)->bool { return LexTryParseString(Out,*Cell(Name)) && FMath::IsFinite(Out); };
        double Initial,Battery,Terminal,Efficiency;
        if (!Number(TEXT("initial_kwh"),Initial) || !Number(TEXT("battery_kwh"),Battery)
            || !Number(TEXT("terminal_kwh"),Terminal) || !Number(TEXT("efficiency"),Efficiency)
            || Battery<=0 || Initial<0 || Initial>Battery || Terminal<0 || Terminal>Battery || Efficiency<=0 || Efficiency>1) return false;
        const FString Id=Cell(TEXT("vehicle_id")); int32 Index;
        if (const int32* Old=Indices.Find(Id)) Index=*Old;
        else
        {
            Index=Vehicles.AddDefaulted(); Indices.Add(Id,Index);
            Vehicles[Index].Id=Id; Vehicles[Index].InitialKWh=Initial; Vehicles[Index].BatteryKWh=Battery;
            Vehicles[Index].TerminalKWh=Terminal; Vehicles[Index].Efficiency=Efficiency;
        }
        FVehicle& V=Vehicles[Index];
        if (!FMath::IsNearlyEqual(V.InitialKWh,Initial) || !FMath::IsNearlyEqual(V.BatteryKWh,Battery)
            || !FMath::IsNearlyEqual(V.TerminalKWh,Terminal) || !FMath::IsNearlyEqual(V.Efficiency,Efficiency)) return false;
        FEvent E; E.TaskId=Cell(TEXT("task_id")); E.Type=Cell(TEXT("event_type")); E.StationId=Cell(TEXT("station_id"));
        if (!Number(TEXT("start"),E.Start) || !Number(TEXT("end"),E.End) || !Number(TEXT("deadline"),E.Deadline)
            || !Number(TEXT("energy_kwh"),E.TractionKWh) || !Number(TEXT("grid_kwh"),E.GridKWh)
            || E.Start<0 || E.End<=E.Start || E.End>24 || E.End>E.Deadline+.0001f || E.TractionKWh<0 || E.GridKWh<0) return false;
        if ((E.Type!=TEXT("drive") && E.Type!=TEXT("charge"))
            || (E.Type==TEXT("drive") && E.GridKWh>0) || (E.Type==TEXT("charge") && E.TractionKWh>0)) return false;
        TArray<FString> PointTexts; Cell(TEXT("path_points")).ParseIntoArray(PointTexts,TEXT(";"),true);
        for (const FString& Point:PointTexts)
        {
            TArray<FString> XYZ; Point.ParseIntoArray(XYZ,TEXT(","),true); FVector P;
            if (XYZ.Num()!=3 || !LexTryParseString(P.X,*XYZ[0]) || !LexTryParseString(P.Y,*XYZ[1])
                || !LexTryParseString(P.Z,*XYZ[2]) || P.ContainsNaN()) return false;
            if (E.Points.Num()) E.LengthCm+=FVector::Dist(E.Points.Last(),P);
            E.Points.Add(P);
        }
        if (E.Points.Num()<2) return false;
        V.Events.Add(MoveTemp(E));
    }
    for (FVehicle& V:Vehicles)
    {
        V.Events.Sort([](const FEvent& A,const FEvent& B){return A.Start<B.Start;});
        double Inventory=V.InitialKWh,Previous=0; FVector Position=V.Events[0].Points[0];
        for (const FEvent& E:V.Events)
        {
            if (E.Start<Previous-.0001f || FVector::Dist(Position,E.Points[0])>2.0f) return false;
            Inventory+=E.GridKWh*V.Efficiency-E.TractionKWh;
            if (Inventory<-.001f || Inventory>V.BatteryKWh+.001f) return false;
            Previous=E.End; Position=E.Points.Last();
        }
        if (FMath::Abs(Inventory-V.TerminalKWh)>.001f) return false;
    }
    return Vehicles.Num()>0;
}

void AScientificEVRuntimeManager::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds); if (bFinished) return;
    Elapsed+=DeltaSeconds; Hour=FMath::Min(24.0,24.0*Elapsed/DaySeconds);
    UpdateVehicles(); Accumulator+=DeltaSeconds;
    if (Accumulator>=.1f || Hour>=24) { WriteSamples(); Accumulator=0; }
    if (Hour>=24)
    {
        bFinished=true;
        UE_LOG(LogStackelbergEV,Display,TEXT("SCIENTIFIC_REPLAY_COMPLETE vehicles=%d"),Vehicles.Num());
        if (FParse::Param(FCommandLine::Get(),TEXT("EVScientificAutoExit"))) FPlatformMisc::RequestExit(false);
    }
}

FVector AScientificEVRuntimeManager::Along(const FEvent& E,double Fraction)
{
    double Remaining=FMath::Clamp(Fraction,0.0,1.0)*E.LengthCm;
    for (int32 I=1; I<E.Points.Num(); ++I)
    {
        const double Length=FVector::Dist(E.Points[I-1],E.Points[I]);
        if (Remaining<=Length && Length>0) return FMath::Lerp(E.Points[I-1],E.Points[I],Remaining/Length);
        Remaining-=Length;
    }
    return E.Points.Last();
}

void AScientificEVRuntimeManager::UpdateVehicles()
{
    for (FVehicle& V:Vehicles)
    {
        V.EnergyKWh=0; V.GridKWh=0; V.ChargingKW=0; V.StationId.Empty(); FVector Position=V.Events[0].Points[0];
        for (const FEvent& E:V.Events)
        {
            if (Hour<E.Start) break;
            const double Fraction=FMath::Clamp((Hour-E.Start)/(E.End-E.Start),0.0,1.0);
            V.EnergyKWh+=E.TractionKWh*Fraction; V.GridKWh+=E.GridKWh*Fraction; Position=Along(E,Fraction);
            if (E.Type==TEXT("charge") && Hour<E.End) { V.ChargingKW=E.GridKWh/(E.End-E.Start); V.StationId=E.StationId; }
        }
        // No clamp: an invalid inventory must remain observable to the audit.
        V.Soc=100.0f*(V.InitialKWh+V.Efficiency*V.GridKWh-V.EnergyKWh)/V.BatteryKWh;
        if (V.Actor.IsValid()) V.Actor->SetActorLocation(Position,false,nullptr,ETeleportType::TeleportPhysics);
    }
}

void AScientificEVRuntimeManager::WriteSamples()
{
    FString Buffer;
    for (const FVehicle& V:Vehicles)
    {
        const FVector P=V.Actor.IsValid()?V.Actor->GetActorLocation():FVector::ZeroVector;
        Buffer+=FString::Printf(TEXT("%.8f,%s,%.8f,%.8f,%.8f,%.8f,%.8f,%s,%.4f,%.4f,%.4f\n"),
            Hour,*Csv(V.Id),V.Soc,V.BatteryKWh,V.EnergyKWh,V.GridKWh,V.ChargingKW,*Csv(V.StationId),P.X,P.Y,P.Z);
    }
    FFileHelper::SaveStringToFile(Buffer,*ObservationPath,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append);
}

FString AScientificEVRuntimeManager::Csv(const FString& S) { return TEXT("\"")+S.Replace(TEXT("\""),TEXT("\"\""))+TEXT("\""); }
bool AScientificEVRuntimeManager::ParseCsv(const FString& Text,TArray<FString>& Out)
{
    Out.Reset(); FString Cell; bool Quoted=false;
    for (int32 I=0; I<Text.Len(); ++I)
    {
        const TCHAR C=Text[I];
        if (C==TEXT('"'))
        {
            if (Quoted && I+1<Text.Len() && Text[I+1]==TEXT('"')) { Cell.AppendChar(C); ++I; } else Quoted=!Quoted;
        }
        else if (C==TEXT(',') && !Quoted) { Out.Add(Cell); Cell.Empty(); } else Cell.AppendChar(C);
    }
    Out.Add(Cell); return !Quoted;
}
