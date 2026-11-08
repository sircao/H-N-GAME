#include "StackelbergEVRuntimeManager.h"

#include "StackelbergEVOptimizationModule.h"
#include "Engine/DirectionalLight.h"
#include "Components/LightComponent.h"
#include "EngineUtils.h"
#include "Interfaces/IPluginManager.h"
#include "HAL/FileManager.h"
#include "Misc/CommandLine.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/DateTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"

namespace
{
const TCHAR* ConfigSection = TEXT("StackelbergEVOptimization");

FString PluginConfigPath()
{
    const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("StackelbergEVOptimization"));
    return Plugin.IsValid()
        ? FPaths::Combine(Plugin->GetBaseDir(), TEXT("Config/DefaultStackelbergEVOptimization.ini"))
        : FString();
}

bool LoadPluginConfig(FConfigFile& OutConfig)
{
    const FString Path = PluginConfigPath();
    if (Path.IsEmpty())
    {
        return false;
    }
    OutConfig.Read(Path);
    return OutConfig.Num() > 0;
}

float PathLength(const TArray<FVector>& Points)
{
    float Total = 0.0f;
    for (int32 Index = 1; Index < Points.Num(); ++Index)
    {
        Total += FVector::Dist(Points[Index - 1], Points[Index]);
    }
    return Total;
}
}

AStackelbergEVRuntimeManager::AStackelbergEVRuntimeManager()
{
    PrimaryActorTick.bCanEverTick = true;
}

bool AStackelbergEVRuntimeManager::IsOptimizedModeEnabled()
{
    FString Mode;
    FConfigFile Config;
    if (LoadPluginConfig(Config))
    {
        Config.GetString(ConfigSection, TEXT("RunMode"), Mode);
    }
    FParse::Value(FCommandLine::Get(), TEXT("EVOptimizationMode="), Mode);
    return Mode.Equals(TEXT("Optimized"), ESearchCase::IgnoreCase);
}

void AStackelbergEVRuntimeManager::BeginPlay()
{
    Super::BeginPlay();

    FString PlanPath;
    if (!IsOptimizedModeEnabled() || !LoadConfiguration(PlanPath))
    {
        SetActorTickEnabled(false);
        return;
    }

    TMap<FString, FVehiclePlan> Plans;
    if (!LoadPlan(PlanPath, Plans) || !BindVehicles(Plans))
    {
        UE_LOG(LogStackelbergEV, Error, TEXT("Optimized mode requested, but no valid runtime plan was loaded. Baseline controller remains active."));
        SetActorTickEnabled(false);
        return;
    }

    DisableBaselineController();
    InitializeOutputFiles();
    UpdateVehicles();
    WriteSamples();
    UE_LOG(LogStackelbergEV, Log, TEXT("Optimized runtime controls %d vehicles using %s"), RuntimeVehicles.Num(), *PlanPath);
}

void AStackelbergEVRuntimeManager::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    ElapsedSeconds += DeltaSeconds;
    const float Span = FMath::Max(SimEndHour - SimStartHour, 0.01f);
    CurrentHour = SimStartHour + FMath::Fmod(ElapsedSeconds, SimDayDurationSeconds) * Span / SimDayDurationSeconds;
    UpdateVehicles();

    SampleAccumulator += DeltaSeconds;
    if (SampleAccumulator >= SampleIntervalSeconds)
    {
        WriteSamples();
        SampleAccumulator = 0.0f;
    }
}

bool AStackelbergEVRuntimeManager::LoadConfiguration(FString& OutPlanPath)
{
    FConfigFile Config;
    if (!LoadPluginConfig(Config))
    {
        UE_LOG(LogStackelbergEV, Error, TEXT("Cannot read plugin configuration."));
        return false;
    }

    FString PlanFile;
    Config.GetString(ConfigSection, TEXT("PlanFile"), PlanFile);
    Config.GetFloat(ConfigSection, TEXT("SimStartHour"), SimStartHour);
    Config.GetFloat(ConfigSection, TEXT("SimEndHour"), SimEndHour);
    Config.GetFloat(ConfigSection, TEXT("SimDayDurationSeconds"), SimDayDurationSeconds);
    Config.GetFloat(ConfigSection, TEXT("SampleIntervalSeconds"), SampleIntervalSeconds);

    SimStartHour = SimStartHour > 0.0f ? SimStartHour : 6.0f;
    SimEndHour = SimEndHour > SimStartHour ? SimEndHour : 23.0f;
    SimDayDurationSeconds = SimDayDurationSeconds > 0.0f ? SimDayDurationSeconds : 420.0f;
    SampleIntervalSeconds = SampleIntervalSeconds > 0.0f ? SampleIntervalSeconds : 2.0f;
    CurrentHour = SimStartHour;

    HourlyPrices.Init(0.70f, 24);
    for (int32 Hour = 0; Hour < 24; ++Hour)
    {
        HourlyPrices[Hour] = Hour < 7 ? 0.35f : ((Hour >= 17 && Hour < 22) ? 1.20f : 0.70f);
    }

    FString CommandLinePlan;
    FParse::Value(FCommandLine::Get(), TEXT("EVOptimizationPlan="), CommandLinePlan);
    if (!CommandLinePlan.IsEmpty())
    {
        PlanFile = CommandLinePlan;
    }
    OutPlanPath = FPaths::IsRelative(PlanFile) ? FPaths::Combine(FPaths::ProjectSavedDir(), PlanFile) : PlanFile;

    const FString PricePath = FPaths::Combine(FPaths::GetPath(OutPlanPath), TEXT("optimal_price_curve.csv"));
    FString PriceText;
    if (FFileHelper::LoadFileToString(PriceText, *PricePath))
    {
        TArray<FString> Lines;
        PriceText.ParseIntoArrayLines(Lines, true);
        for (int32 Index = 1; Index < Lines.Num(); ++Index)
        {
            TArray<FString> Fields;
            if (ParseCsvLine(Lines[Index], Fields) && Fields.Num() >= 2)
            {
                const int32 Hour = FCString::Atoi(*Fields[0]);
                if (HourlyPrices.IsValidIndex(Hour))
                {
                    HourlyPrices[Hour] = FCString::Atof(*Fields[1]);
                }
            }
        }
    }
    return true;
}

bool AStackelbergEVRuntimeManager::LoadPlan(const FString& PlanPath, TMap<FString, FVehiclePlan>& OutPlans) const
{
    FString Text;
    if (!FFileHelper::LoadFileToString(Text, *PlanPath))
    {
        UE_LOG(LogStackelbergEV, Error, TEXT("Optimization plan not found: %s"), *PlanPath);
        return false;
    }

    TArray<FString> Lines;
    Text.ParseIntoArrayLines(Lines, true);
    if (Lines.Num() < 2)
    {
        return false;
    }

    TArray<FString> Header;
    ParseCsvLine(Lines[0], Header);
    TMap<FString, int32> Column;
    for (int32 Index = 0; Index < Header.Num(); ++Index)
    {
        Column.Add(Header[Index], Index);
    }
    const TCHAR* Required[] = {
        TEXT("vehicle_id"), TEXT("route_id"), TEXT("path_points"), TEXT("departure_hour"),
        TEXT("arrival_hour"), TEXT("charging_start_hour"), TEXT("charging_end_hour"),
        TEXT("charging_energy_kwh"), TEXT("carbon_price")
    };
    for (const TCHAR* Name : Required)
    {
        if (!Column.Contains(Name))
        {
            UE_LOG(LogStackelbergEV, Error, TEXT("Optimization plan is missing column %s"), Name);
            return false;
        }
    }

    for (int32 LineIndex = 1; LineIndex < Lines.Num(); ++LineIndex)
    {
        TArray<FString> Fields;
        if (!ParseCsvLine(Lines[LineIndex], Fields) || Fields.Num() < Header.Num())
        {
            continue;
        }
        FVehiclePlan Plan;
        Plan.VehicleId = Fields[Column[TEXT("vehicle_id")]].RightPad(4).Left(4);
        Plan.RouteId = Fields[Column[TEXT("route_id")]];
        Plan.DepartureHour = FCString::Atof(*Fields[Column[TEXT("departure_hour")]]);
        Plan.ArrivalHour = FCString::Atof(*Fields[Column[TEXT("arrival_hour")]]);
        Plan.ChargingStartHour = FCString::Atof(*Fields[Column[TEXT("charging_start_hour")]]);
        Plan.ChargingEndHour = FCString::Atof(*Fields[Column[TEXT("charging_end_hour")]]);
        Plan.ChargingEnergyKWh = FCString::Atof(*Fields[Column[TEXT("charging_energy_kwh")]]);
        Plan.CarbonPrice = FCString::Atof(*Fields[Column[TEXT("carbon_price")]]);
        if (!ParsePath(Fields[Column[TEXT("path_points")]], Plan.PathPoints))
        {
            continue;
        }
        Plan.PathLengthCm = PathLength(Plan.PathPoints);
        OutPlans.Add(Plan.VehicleId, MoveTemp(Plan));
    }
    return OutPlans.Num() > 0;
}

bool AStackelbergEVRuntimeManager::BindVehicles(const TMap<FString, FVehiclePlan>& Plans)
{
    RuntimeVehicles.Reset();
    for (TActorIterator<AActor> It(GetWorld()); It; ++It)
    {
        AActor* Actor = *It;
        if (!IsValid(Actor))
        {
            continue;
        }
        const FString VehicleId = VehicleIdFromLabel(Actor->GetActorLabel());
        const FVehiclePlan* Plan = Plans.Find(VehicleId);
        if (Plan == nullptr)
        {
            continue;
        }
        FRuntimeVehicle Runtime;
        Runtime.Actor = Actor;
        Runtime.Plan = *Plan;
        RuntimeVehicles.Add(MoveTemp(Runtime));
    }
    return RuntimeVehicles.Num() > 0;
}

void AStackelbergEVRuntimeManager::DisableBaselineController()
{
    for (TActorIterator<AActor> It(GetWorld()); It; ++It)
    {
        AActor* Actor = *It;
        if (IsValid(Actor) && Actor->GetClass()->GetName().Contains(TEXT("EVTrafficRuntimeController")))
        {
            Actor->SetActorTickEnabled(false);
            UE_LOG(LogStackelbergEV, Log, TEXT("Baseline controller tick disabled for optimized Play: %s"), *Actor->GetName());
        }
    }
}

void AStackelbergEVRuntimeManager::UpdateVehicles()
{
    const bool bNight = CurrentHour >= 19.0f;
    for (TActorIterator<ADirectionalLight> It(GetWorld()); It; ++It)
    {
        if (IsValid(*It))
        {
            (*It)->GetLightComponent()->SetVisibility(!bNight);
        }
    }

    for (FRuntimeVehicle& Runtime : RuntimeVehicles)
    {
        AActor* Actor = Runtime.Actor.Get();
        if (!IsValid(Actor))
        {
            continue;
        }
        const float Duration = FMath::Max(Runtime.Plan.ArrivalHour - Runtime.Plan.DepartureHour, 0.01f);
        const float Progress = FMath::Clamp((CurrentHour - Runtime.Plan.DepartureHour) / Duration, 0.0f, 1.0f);
        FVector Direction;
        int32 Segment = 0;
        const FVector Position = PositionOnPath(Runtime.Plan, Progress, Direction, Segment);
        const FRotator Rotation(0.0f, Direction.Rotation().Yaw, 0.0f);
        Actor->SetActorLocationAndRotation(Position, Rotation, false, nullptr, ETeleportType::TeleportPhysics);
        Runtime.DistanceKm = Runtime.Plan.PathLengthCm * Progress / 100000.0f;
        Runtime.EnergyKWh = Runtime.DistanceKm * 0.16f;
        Runtime.Soc = FMath::Clamp(85.0f - Runtime.EnergyKWh / 65.0f * 100.0f, 0.0f, 100.0f);
        Runtime.SegmentIndex = Segment;
    }
}

void AStackelbergEVRuntimeManager::InitializeOutputFiles()
{
    RunStamp = FDateTime::Now().ToString(TEXT("%Y%m%d_%H%M%S"));
    const FString Directory = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("EVTrafficSamples"));
    IFileManager::Get().MakeDirectory(*Directory, true);
    VehicleCsvPath = FPaths::Combine(Directory, FString::Printf(TEXT("datalist_%s.csv"), *RunStamp));
    RoadCsvPath = FPaths::Combine(Directory, FString::Printf(TEXT("road_%s.csv"), *RunStamp));
    ChargingCsvPath = FPaths::Combine(Directory, FString::Printf(TEXT("charging_%s.csv"), *RunStamp));
    SystemCsvPath = FPaths::Combine(Directory, FString::Printf(TEXT("system_%s.csv"), *RunStamp));
    BehaviorCsvPath = FPaths::Combine(Directory, FString::Printf(TEXT("behavior_%s.csv"), *RunStamp));
    FFileHelper::SaveStringToFile(TEXT("timestamp_utc,elapsed_sec,sim_hour,vehicle_id,vehicle_type,lon,lat,z_cm,speed,acceleration,heading,road_segment_id,cumulative_energy_kWh,instantaneous_power_kW,soc,is_charging,charging_power_kW,battery_capacity_kWh,od_origin,od_destination,departure_time,route_id\n"), *VehicleCsvPath);
    FFileHelper::SaveStringToFile(TEXT("timestamp_utc,road_segment_id,vehicle_count,vehicle_ids,average_speed,capacity,free_flow_time,length\n"), *RoadCsvPath);
    FFileHelper::SaveStringToFile(TEXT("timestamp_utc,charging_station_id,charger_id,vehicle_id,charging_start_time,charging_end_time,charging_power_kW,energy_delivered_kWh,queue_vehicle_ids,charging_price,station_capacity\n"), *ChargingCsvPath);
    FFileHelper::SaveStringToFile(TEXT("timestamp_utc,active_vehicle_count,total_energy_kWh,total_charging_load_kW,total_distance_km,electricity_price\n"), *SystemCsvPath);
    FFileHelper::SaveStringToFile(TEXT("timestamp_utc,beta_T,lambda,carbon_price,route_choice_model,charging_decision_rule\n"), *BehaviorCsvPath);
}

void AStackelbergEVRuntimeManager::WriteSamples()
{
    const FString Timestamp = FDateTime::UtcNow().ToString(TEXT("%Y-%m-%dT%H:%M:%SZ"));
    FString VehicleBuffer;
    FString RoadBuffer;
    FString ChargingBuffer;
    TMap<FString, TArray<FString>> EdgeVehicles;
    float TotalEnergy = 0.0f;
    float TotalDistance = 0.0f;
    float ChargingLoad = 0.0f;
    float CarbonPrice = 45.0f;

    for (const FRuntimeVehicle& Runtime : RuntimeVehicles)
    {
        const AActor* Actor = Runtime.Actor.Get();
        if (!IsValid(Actor))
        {
            continue;
        }
        const FVector Position = Actor->GetActorLocation();
        const bool IsCharging = Runtime.Plan.ChargingStartHour >= 0.0f && CurrentHour >= Runtime.Plan.ChargingStartHour && CurrentHour < Runtime.Plan.ChargingEndHour;
        const float ChargingPower = IsCharging ? Runtime.Plan.ChargingEnergyKWh / FMath::Max(Runtime.Plan.ChargingEndHour - Runtime.Plan.ChargingStartHour, 0.01f) : 0.0f;
        const FString EdgeId = FString::Printf(TEXT("%s_E%03d"), *Runtime.Plan.RouteId, Runtime.SegmentIndex);
        EdgeVehicles.FindOrAdd(EdgeId).Add(Runtime.Plan.VehicleId);
        TotalEnergy += Runtime.EnergyKWh;
        TotalDistance += Runtime.DistanceKm;
        ChargingLoad += ChargingPower;
        CarbonPrice = Runtime.Plan.CarbonPrice;
        VehicleBuffer += FString::Printf(
            TEXT("%s,%.3f,%.4f,%s,EV,%.3f,%.3f,%.3f,0,0,%.3f,%s,%.6f,0,%.3f,%d,%.6f,65,%s,%s,%.4f,%s\n"),
            *CsvCell(Timestamp), ElapsedSeconds, CurrentHour, *CsvCell(Runtime.Plan.VehicleId), Position.X, Position.Y, Position.Z,
            Actor->GetActorRotation().Yaw, *CsvCell(EdgeId), Runtime.EnergyKWh, Runtime.Soc, IsCharging ? 1 : 0, ChargingPower,
            *CsvCell(Runtime.Plan.PathPoints.Num() ? Runtime.Plan.PathPoints[0].ToString() : TEXT("")),
            *CsvCell(Runtime.Plan.PathPoints.Num() ? Runtime.Plan.PathPoints.Last().ToString() : TEXT("")),
            Runtime.Plan.DepartureHour, *CsvCell(Runtime.Plan.RouteId));
        if (IsCharging)
        {
            ChargingBuffer += FString::Printf(TEXT("%s,%s,%s,%s,%.4f,%.4f,%.6f,%.6f,%s,%.3f,%d\n"),
                *CsvCell(Timestamp), *CsvCell(TEXT("OPTIMIZED_GRID")), *CsvCell(TEXT("OPTIMIZED_GRID")), *CsvCell(Runtime.Plan.VehicleId),
                Runtime.Plan.ChargingStartHour, Runtime.Plan.ChargingEndHour, ChargingPower,
                Runtime.Plan.ChargingEnergyKWh, *CsvCell(TEXT("")), ElectricityPrice(CurrentHour), RuntimeVehicles.Num());
        }
    }

    for (const TPair<FString, TArray<FString>>& Entry : EdgeVehicles)
    {
        RoadBuffer += FString::Printf(TEXT("%s,%s,%d,%s,0,12,0,0\n"), *CsvCell(Timestamp), *CsvCell(Entry.Key), Entry.Value.Num(), *CsvCell(FString::Join(Entry.Value, TEXT("|"))));
    }
    if (ChargingBuffer.IsEmpty())
    {
        ChargingBuffer = FString::Printf(TEXT("%s,%s,%s,%s,%s,%s,0,0,%s,%.3f,%d\n"), *CsvCell(Timestamp), *CsvCell(TEXT("OPTIMIZED_GRID")), *CsvCell(TEXT("OPTIMIZED_GRID")), *CsvCell(TEXT("")), *CsvCell(TEXT("")), *CsvCell(TEXT("")), *CsvCell(TEXT("")), ElectricityPrice(CurrentHour), RuntimeVehicles.Num());
    }
    const FString SystemLine = FString::Printf(TEXT("%s,%d,%.6f,%.6f,%.6f,%.3f\n"), *CsvCell(Timestamp), RuntimeVehicles.Num(), TotalEnergy, ChargingLoad, TotalDistance, ElectricityPrice(CurrentHour));
    const FString BehaviorLine = FString::Printf(TEXT("%s,52.50,1.00,%.3f,Stackelberg-MNL-Wardrop,Optimized price-responsive schedule\n"), *CsvCell(Timestamp), CarbonPrice);
    FFileHelper::SaveStringToFile(VehicleBuffer, *VehicleCsvPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
    FFileHelper::SaveStringToFile(RoadBuffer, *RoadCsvPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
    FFileHelper::SaveStringToFile(ChargingBuffer, *ChargingCsvPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
    FFileHelper::SaveStringToFile(SystemLine, *SystemCsvPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
    FFileHelper::SaveStringToFile(BehaviorLine, *BehaviorCsvPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
}

float AStackelbergEVRuntimeManager::ElectricityPrice(float Hour) const
{
    return HourlyPrices.IsValidIndex(FMath::Clamp(FMath::FloorToInt(Hour), 0, 23)) ? HourlyPrices[FMath::Clamp(FMath::FloorToInt(Hour), 0, 23)] : 0.70f;
}

bool AStackelbergEVRuntimeManager::ParseCsvLine(const FString& Line, TArray<FString>& OutFields)
{
    OutFields.Reset();
    FString Field;
    bool InQuotes = false;
    for (int32 Index = 0; Index < Line.Len(); ++Index)
    {
        const TCHAR Character = Line[Index];
        if (Character == TEXT('"'))
        {
            if (InQuotes && Index + 1 < Line.Len() && Line[Index + 1] == TEXT('"'))
            {
                Field.AppendChar(TEXT('"'));
                ++Index;
            }
            else
            {
                InQuotes = !InQuotes;
            }
        }
        else if (Character == TEXT(',') && !InQuotes)
        {
            OutFields.Add(Field);
            Field.Reset();
        }
        else
        {
            Field.AppendChar(Character);
        }
    }
    OutFields.Add(Field);
    return !InQuotes;
}

bool AStackelbergEVRuntimeManager::ParsePath(const FString& Text, TArray<FVector>& OutPoints)
{
    OutPoints.Reset();
    TArray<FString> PointStrings;
    Text.ParseIntoArray(PointStrings, TEXT(";"), true);
    for (const FString& PointText : PointStrings)
    {
        TArray<FString> Coordinates;
        PointText.ParseIntoArray(Coordinates, TEXT(","), true);
        if (Coordinates.Num() == 3)
        {
            OutPoints.Add(FVector(FCString::Atof(*Coordinates[0]), FCString::Atof(*Coordinates[1]), FCString::Atof(*Coordinates[2])));
        }
    }
    return OutPoints.Num() >= 2;
}

FString AStackelbergEVRuntimeManager::VehicleIdFromLabel(const FString& Label)
{
    if (!Label.StartsWith(TEXT("EVSim_")))
    {
        return FString();
    }
    TArray<FString> Parts;
    Label.ParseIntoArray(Parts, TEXT("_"), true);
    return Parts.Num() >= 2 ? Parts[1] : FString();
}

FVector AStackelbergEVRuntimeManager::PositionOnPath(const FVehiclePlan& Plan, float Progress, FVector& OutDirection, int32& OutSegment)
{
    float Remaining = FMath::Clamp(Progress, 0.0f, 1.0f) * Plan.PathLengthCm;
    OutDirection = FVector::ForwardVector;
    OutSegment = 0;
    for (int32 Index = 1; Index < Plan.PathPoints.Num(); ++Index)
    {
        const FVector Start = Plan.PathPoints[Index - 1];
        const FVector End = Plan.PathPoints[Index];
        const float Length = FVector::Dist(Start, End);
        if (Length <= KINDA_SMALL_NUMBER)
        {
            continue;
        }
        OutDirection = (End - Start).GetSafeNormal2D();
        OutSegment = Index - 1;
        if (Remaining <= Length)
        {
            return FMath::Lerp(Start, End, Remaining / Length);
        }
        Remaining -= Length;
    }
    return Plan.PathPoints.Num() ? Plan.PathPoints.Last() : FVector::ZeroVector;
}

FString AStackelbergEVRuntimeManager::CsvCell(const FString& Value)
{
    FString Escaped = Value;
    Escaped.ReplaceInline(TEXT("\""), TEXT("\"\""));
    return FString::Printf(TEXT("\"%s\""), *Escaped);
}
