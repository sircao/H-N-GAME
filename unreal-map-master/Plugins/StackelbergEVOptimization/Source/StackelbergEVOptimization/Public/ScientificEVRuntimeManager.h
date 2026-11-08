#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "ScientificEVRuntimeManager.generated.h"

// Finite physical event replay. It is not independent traffic validation.
UCLASS(NotBlueprintable)
class STACKELBERGEVOPTIMIZATION_API AScientificEVRuntimeManager final : public AActor
{
    GENERATED_BODY()
public:
    AScientificEVRuntimeManager();
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;
private:
    struct FEvent
    {
        FString TaskId, Type, StationId;
        double Start=0, End=0, Deadline=24, TractionKWh=0, GridKWh=0, LengthCm=0;
        TArray<FVector> Points;
    };
    struct FVehicle
    {
        FString Id, StationId;
        TWeakObjectPtr<AActor> Actor;
        TArray<FEvent> Events;
        double InitialKWh=0, BatteryKWh=0, TerminalKWh=0, Efficiency=1;
        double EnergyKWh=0, GridKWh=0, Soc=0, ChargingKW=0;
    };
    TArray<FVehicle> Vehicles;
    FString ObservationPath;
    double Hour=0, Elapsed=0, DaySeconds=24, Accumulator=0;
    bool bFinished=false;
    bool LoadPlan(const FString& Path);
    void UpdateVehicles();
    void WriteSamples();
    static bool ParseCsv(const FString& Text,TArray<FString>& Out);
    static FString Csv(const FString& Value);
    static FVector Along(const FEvent& Event,double Fraction);
};
