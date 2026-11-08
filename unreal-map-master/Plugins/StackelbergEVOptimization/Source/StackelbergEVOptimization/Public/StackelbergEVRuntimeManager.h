#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "StackelbergEVRuntimeManager.generated.h"

UCLASS(NotBlueprintable)
class STACKELBERGEVOPTIMIZATION_API AStackelbergEVRuntimeManager final : public AActor
{
    GENERATED_BODY()

public:
    AStackelbergEVRuntimeManager();

    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;

    static bool IsOptimizedModeEnabled();

private:
    struct FVehiclePlan
    {
        FString VehicleId;
        FString RouteId;
        TArray<FVector> PathPoints;
        float PathLengthCm = 0.0f;
        float DepartureHour = 6.0f;
        float ArrivalHour = 7.0f;
        float ChargingStartHour = -1.0f;
        float ChargingEndHour = -1.0f;
        float ChargingEnergyKWh = 0.0f;
        float CarbonPrice = 45.0f;
    };

    struct FRuntimeVehicle
    {
        TWeakObjectPtr<AActor> Actor;
        FVehiclePlan Plan;
        float DistanceKm = 0.0f;
        float EnergyKWh = 0.0f;
        float Soc = 80.0f;
        int32 SegmentIndex = 0;
    };

    TArray<FRuntimeVehicle> RuntimeVehicles;
    float SimStartHour = 6.0f;
    float SimEndHour = 23.0f;
    float SimDayDurationSeconds = 420.0f;
    float CurrentHour = 6.0f;
    float ElapsedSeconds = 0.0f;
    float SampleAccumulator = 0.0f;
    float SampleIntervalSeconds = 2.0f;
    FString RunStamp;
    FString VehicleCsvPath;
    FString RoadCsvPath;
    FString ChargingCsvPath;
    FString SystemCsvPath;
    FString BehaviorCsvPath;
    TArray<float> HourlyPrices;

    bool LoadConfiguration(FString& OutPlanPath);
    bool LoadPlan(const FString& PlanPath, TMap<FString, FVehiclePlan>& OutPlans) const;
    bool BindVehicles(const TMap<FString, FVehiclePlan>& Plans);
    void DisableBaselineController();
    void InitializeOutputFiles();
    void WriteSamples();
    void UpdateVehicles();
    float ElectricityPrice(float Hour) const;

    static bool ParseCsvLine(const FString& Line, TArray<FString>& OutFields);
    static bool ParsePath(const FString& Text, TArray<FVector>& OutPoints);
    static FString VehicleIdFromLabel(const FString& Label);
    static FVector PositionOnPath(const FVehiclePlan& Plan, float Progress, FVector& OutDirection, int32& OutSegment);
    static FString CsvCell(const FString& Value);
};
