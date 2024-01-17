from torchvision.utils import make_grid
from torch.utils.data import DataLoader

from torchvision import transforms
import time
import datetime
from torch.autograd import Variable
import tools
import numpy as np

# 设置路径
dataSourcePath = "dataSet1/brain/"
dataSavePath = "output/"
pthLoadPath = ""
device=torch.device("cuda:0")
# device=torch.device("cpu")

# 使用前清除cuda缓存
torch.cuda.empty_cache()
torch.manual_seed(0)

# 对3d卷积神经网络的权重初始化
def weights_init(m):
    if isinstance(m, nn.Conv3d) or isinstance(m, nn.ConvTranspose3d):
        torch.nn.init.normal_(m.weight, 0.0, 0.02)
    if isinstance(m, nn.BatchNorm3d):
        torch.nn.init.normal_(m.weight, 0.0, 0.02)
        torch.nn.init.constant_(m.bias, 0)


#模型的代码实现见VCNet_model.py
from VCNet.VCNet_model import *

# Feel free to change pretrained to False if you're training the model from scratch
pretrained = False
save_model = True

fileStartVal = 1
fileIncrement = 1
constVal = 1
total_gen_loss = []
total_disc_loss = []


#---------------------initialize the model----------------------
# 1) parameters for dataset
total_index = 100
ratio_for_train = 0.7
max_train_index = round(total_index*ratio_for_train)
dim = (160, 224, 168)   # [depth, height, width]. brain
float32DataType = np.float32

trainDataset = tools.DataSet(data_path="",
                             mask_type="test",
                             prefix="norm_ct",
                             data_type="raw",
                             volume_shape=dim,
                             max_index=70)

# 2) parameters for loss function
Loss_G_rec = tools.WeightedMSELoss().to(device)
Loss_G_Adv = tools.AdversarialGLoss().to(device)
Loss_D_Adv = tools.AdversarialDLoss().to(device)

# 3) other parameters
lambda_recon = 200
n_epochs = 400
input_dim = 1
real_dim = 1
batch_size = 1          #原模型参数 10
# lr = 5e-3             #learn rate 原模型参数 5e-3(0.005)
lr = 0.0001
weight_decay_adv = 0.001
weight_decay_rec = 1

display_step = np.ceil(np.ceil(max_train_index / batch_size) * n_epochs / 20)   #一共输出20个epoch，供判断用


# 4) send parameters to cuda
gen = UNet_v2(in_channel=1).to(device)
gen_opt = torch.optim.Adam(gen.parameters(), lr=lr,betas=(0.9,0.999),weight_decay=weight_decay_rec)

disc = Dis_VCNet().to(device)
disc_opt = torch.optim.Adam(disc.parameters(), lr=lr,betas=(0.9,0.999),weight_decay=weight_decay_adv)

print("initialize finished")

#---------------------------------training------------------------
if pretrained:
    loaded_state = torch.load(pthLoadPath)
    gen.load_state_dict(loaded_state["gen"])
    gen_opt.load_state_dict(loaded_state["gen_opt"])
    disc.load_state_dict(loaded_state["disc"])
    disc_opt.load_state_dict(loaded_state["disc_opt"])
else:
    gen = gen.apply(weights_init)
    disc = disc.apply(weights_init)
    
def pre_train(save_model=True):
    # read the start time
    ot = time.time()
    t1 = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    print("## pre train start##  time:",t1)
    
    dataloader = DataLoader(trainDataset, batch_size=batch_size, shuffle=True)
    gen_opt.param_groups[0]['weight_decay'] = weight_decay_rec
    
    cur_step = 0

    for epoch in range(n_epochs):
        # Dataloader returns the batches
        for real_volume,masked_volume,mask,index in dataloader:

            # wrap them into torch.tensor
            real_volume = torch.tensor(real_volume,requires_grad=True).to(device)
            masked_volume = torch.tensor(masked_volume,requires_grad=True).to(device)
            # mask = torch.tensor(mask,requires_grad=True).to(device)
            output_volume = gen(masked_volume)
            
            # update the generator only
            gen_loss = Loss_G_rec(real_volume,output_volume)
            total_gen_loss.append(gen_loss)
            print("Weighted MSE Loss:", gen_loss.item())
            
            gen_opt.zero_grad()  # Zero out the gradient before back propagation
            gen_loss.backward()
            gen_opt.step()
            
            ### save model and generated volume(if need) ###
            if (cur_step+1) % display_step == 0 or cur_step == 1:
                
                t = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

                # compute time
                dt = time.time() - ot
                elapsedTime = str(datetime.timedelta(seconds=dt))
                per_epoch = str(datetime.timedelta(seconds=dt / (epoch+1)))
                print(f"    epoch = {epoch}     dt={elapsedTime}    per-epoch={per_epoch}")
                
                # save generated volume
                tools.saveRawFile10(f"{dataSavePath}/VCNet_{epoch}",
                                    f"vol_{cur_step:03d}_fake",
                                    output_volume[0, 0, :, :, :])
                
                tools.saveRawFile10(f"{dataSavePath}/{epoch}",
                                    f"vol_{cur_step:03d}_true",
                                    real_volume[0, 0, :, :, :])
                
                tools.saveRawFile10(f"{dataSavePath}/{epoch}",
                                    f"vol_{cur_step:03d}_masked",
                                    masked_volume[0, 0, :, :, :])


                mean_generator_loss = 0
                mean_discriminator_loss = 0
                # You can change save_model to True if you'd like to save the model
                if save_model:
                    fileName = f"{dataSavePath}/{fileName}.pth"
                    torch.save({'gen': gen.state_dict(),
                                'gen_opt': gen_opt.state_dict(),
                                'disc': disc.state_dict(),
                                'disc_opt': disc_opt.state_dict(),
                                }, fileName)
                    
            cur_step += 1
            

    t2 = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    print("##train finished(brain)##  time:",t2)
    print("total train time:")
    print("start:",t1)
    print("end:",t2)
    
    
def fine_tune(save_model=True):
    # read the start time
    ot = time.time()
    t1 = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    print("##fine tune train start##  time:",t1)
    
    mean_generator_loss = 0
    mean_discriminator_loss = 0
    
    dataloader = DataLoader(trainDataset, batch_size=batch_size, shuffle=True)
    gen_opt.param_groups[0]['weight_decay'] = weight_decay_adv

    for epoch in range(n_epochs):
        # Dataloader returns the batches
        for real_volume,masked_volume,mask,index in dataloader:

            # wrap them into torch.tensor
            real_volume = torch.tensor(real_volume,requires_grad=True).to(device)
            masked_volume = torch.tensor(masked_volume,requires_grad=True).to(device)
            mask = torch.tensor(mask,requires_grad=True).to(device)
            output_volume = gen(masked_volume)
            
            # update disc
            disc_loss = Loss_D_Adv(real_dim,output_volume,masked_volume,mask)
            total_disc_loss.append(disc_loss)
            print("Adv Disc Loss:", disc_loss.item())
            
            disc_opt.zero_grad()  # Zero out the gradient before back propagation
            disc_loss.backward()
            disc_opt.step()
            
            # update gen
            gen_loss = Loss_G_Adv(output_volume,masked_volume,mask,real_volume)
            total_gen_loss.append(gen_loss)
            print("Adv Gen Loss:", gen_loss.item())
            
            gen_opt.zero_grad()
            gen_loss.backward()
            gen_opt.step()

            
# when to train? how to swift train mode???????