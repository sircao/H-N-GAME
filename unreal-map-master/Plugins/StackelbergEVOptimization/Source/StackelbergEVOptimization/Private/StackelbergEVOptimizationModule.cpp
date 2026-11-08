#include "StackelbergEVOptimizationModule.h"

#include "StackelbergEVRuntimeManager.h"
#include "ScientificEVRuntimeManager.h"
#include "Engine/World.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

DEFINE_LOG_CATEGORY(LogStackelbergEV);

void FStackelbergEVOptimizationModule::StartupModule()
{
    WorldInitializationHandle = FWorldDelegates::OnPostWorldInitialization.AddLambda(
        [](UWorld* World, const UWorld::InitializationValues)
        {
            if (World == nullptr || (World->WorldType != EWorldType::Game && World->WorldType != EWorldType::PIE))
            {
                return;
            }
            FString ScientificPlan;
            FParse::Value(FCommandLine::Get(), TEXT("EVScientificPlan="), ScientificPlan);
            if (!ScientificPlan.IsEmpty())
            {
                World->SpawnActor<AScientificEVRuntimeManager>();
            }
            else if (AStackelbergEVRuntimeManager::IsOptimizedModeEnabled())
            {
                UE_LOG(LogStackelbergEV, Error, TEXT("Legacy optimized replay is disabled: use an audited scientific event plan via -EVScientificPlan. Baseline is retained for historical comparison only."));
            }
        });
    UE_LOG(LogStackelbergEV, Log, TEXT("Stackelberg EV Optimization module loaded. Baseline remains the default mode."));
}

void FStackelbergEVOptimizationModule::ShutdownModule()
{
    if (WorldInitializationHandle.IsValid())
    {
        FWorldDelegates::OnPostWorldInitialization.Remove(WorldInitializationHandle);
        WorldInitializationHandle.Reset();
    }
}

IMPLEMENT_MODULE(FStackelbergEVOptimizationModule, StackelbergEVOptimization)
